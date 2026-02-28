#!/usr/bin/env python3
import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from urllib.parse import quote
from typing import Any

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

VIDEO_EXTS = {"mkv", "mp4", "avi", "m4v", "mov", "webm"}


@dataclass
class Config:
    discord_token: str
    bot_name: str
    slskd_base_url: str
    slskd_user: str
    slskd_password: str
    ingress_root: str
    batch_max_users: int
    batch_search_timeout_ms: int
    batch_response_wait_sec: int
    batch_start_timeout_sec: int
    batch_min_start_bytes: int


def cfg() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required")
    return Config(
        discord_token=token,
        bot_name=os.getenv("BOT_NAME", "soulmane").strip() or "soulmane",
        slskd_base_url=os.getenv("SLSKD_BASE_URL", "http://127.0.0.1:5030").rstrip("/"),
        slskd_user=os.getenv("SLSKD_WEB_USERNAME", "gary"),
        slskd_password=os.getenv("SLSKD_WEB_PASSWORD", ""),
        ingress_root=os.getenv("INGRESS_ROOT", "/srv/media-ingress/gary"),
        batch_max_users=int(os.getenv("BATCH_MAX_USERS", "5")),
        batch_search_timeout_ms=int(os.getenv("BATCH_SEARCH_TIMEOUT_MS", "30000")),
        batch_response_wait_sec=int(os.getenv("BATCH_RESPONSE_WAIT_SEC", "20")),
        batch_start_timeout_sec=int(os.getenv("BATCH_START_TIMEOUT_SEC", "90")),
        batch_min_start_bytes=int(os.getenv("BATCH_MIN_START_BYTES", "8388608")),
    )


class JobsDB:
    def __init__(self, path: str = "jobs.db") -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              query TEXT NOT NULL,
              state TEXT NOT NULL,
              winner_user TEXT,
              winner_transfer_id TEXT,
              winner_filename TEXT,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              notes TEXT
            );
            CREATE TABLE IF NOT EXISTS job_transfers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id INTEGER NOT NULL,
              username TEXT NOT NULL,
              transfer_id TEXT NOT NULL,
              filename TEXT,
              size INTEGER,
              state TEXT,
              bytes INTEGER DEFAULT 0,
              FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            """
        )
        self._conn.commit()

    def create_job(self, query: str) -> int:
        now = int(time.time())
        cur = self._conn.execute(
            "INSERT INTO jobs(query,state,created_at,updated_at) VALUES(?,?,?,?)",
            (query, "searching", now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def set_job_state(self, job_id: int, state: str, notes: str | None = None) -> None:
        self._conn.execute(
            "UPDATE jobs SET state=?, notes=?, updated_at=? WHERE id=?",
            (state, notes, int(time.time()), job_id),
        )
        self._conn.commit()

    def set_winner(self, job_id: int, username: str, transfer_id: str, filename: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET winner_user=?, winner_transfer_id=?, winner_filename=?, updated_at=? WHERE id=?",
            (username, transfer_id, filename, int(time.time()), job_id),
        )
        self._conn.commit()

    def add_transfer(self, job_id: int, username: str, transfer_id: str, filename: str, size: int) -> None:
        self._conn.execute(
            "INSERT INTO job_transfers(job_id,username,transfer_id,filename,size,state,bytes) VALUES(?,?,?,?,?,?,?)",
            (job_id, username, transfer_id, filename, size, "queued", 0),
        )
        self._conn.commit()

    def update_transfer(self, username: str, transfer_id: str, state: str, b: int) -> None:
        self._conn.execute(
            "UPDATE job_transfers SET state=?, bytes=? WHERE username=? AND transfer_id=?",
            (state, b, username, transfer_id),
        )
        self._conn.commit()

    def job(self, job_id: int) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def transfers(self, job_id: int) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM job_transfers WHERE job_id=?", (job_id,)).fetchall()

    def latest_job(self) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()


class SlskdClient:
    def __init__(self, config: Config):
        self.c = config
        self.s: aiohttp.ClientSession | None = None
        self.token: str | None = None

    async def ensure_session(self) -> aiohttp.ClientSession:
        if self.s is None or self.s.closed:
            self.s = aiohttp.ClientSession()
        return self.s

    async def close(self):
        if self.s and not self.s.closed:
            await self.s.close()

    async def login(self) -> None:
        s = await self.ensure_session()
        async with s.post(
            f"{self.c.slskd_base_url}/api/v0/session",
            json={"username": self.c.slskd_user, "password": self.c.slskd_password},
            timeout=15,
        ) as r:
            r.raise_for_status()
            data = await r.json()
            self.token = data["token"]
            s.headers.update({"Authorization": f"Bearer {self.token}"})

    async def post(self, path: str, **kwargs):
        s = await self.ensure_session()
        async with s.post(f"{self.c.slskd_base_url}{path}", timeout=20, **kwargs) as r:
            r.raise_for_status()
            return await r.json()

    async def get(self, path: str, **kwargs):
        s = await self.ensure_session()
        async with s.get(f"{self.c.slskd_base_url}{path}", timeout=20, **kwargs) as r:
            r.raise_for_status()
            return await r.json()

    async def delete(self, path: str, **kwargs):
        s = await self.ensure_session()
        async with s.delete(f"{self.c.slskd_base_url}{path}", timeout=20, **kwargs) as r:
            if r.status not in (200, 204):
                text = await r.text()
                raise RuntimeError(f"delete failed {r.status}: {text}")


def pick_candidates(responses: list[dict[str, Any]], query: str, max_users: int) -> list[tuple]:
    qtokens = [t for t in query.lower().split() if len(t) >= 3][:5]
    scored = []
    for r in responses:
        user = r.get("username")
        if not user:
            continue
        qlen = int(r.get("queueLength") or 999999)
        free = bool(r.get("hasFreeUploadSlot"))
        for f in r.get("files", []):
            fn = (f.get("filename") or "")
            low = fn.lower()
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            if ext not in VIDEO_EXTS:
                continue
            if qtokens and not any(tok in low for tok in qtokens):
                continue
            size = int(f.get("size") or 0)
            score = (35 if free else 0) + max(0, 20 - min(qlen, 20)) + min(size // (350 * 1024**2), 12)
            scored.append((score, user, qlen, free, size, fn, f))

    out, seen = [], set()
    for item in sorted(scored, reverse=True):
        user = item[1]
        if user in seen:
            continue
        out.append(item)
        seen.add(user)
        if len(out) >= max_users:
            break
    return out


def extract_transfer_map(transfers_payload: list[dict[str, Any]], wanted: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    m: dict[tuple[str, str], dict[str, Any]] = {}
    for t in transfers_payload:
        user = t.get("username")
        for d in t.get("directories", []):
            for f in d.get("files", []):
                key = (user, f.get("id"))
                if key in wanted:
                    m[key] = f
    return m


class SoulmaneBot(discord.Client):
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.config = config
        self.db = JobsDB("jobs.db")
        self.slskd = SlskdClient(config)

    async def setup_hook(self):
        await self.slskd.login()
        # Prevent stale registration/signature mismatches after updates.
        self.tree.clear_commands(guild=None)
        self.tree.add_command(self.download)
        self.tree.add_command(self.status)
        self.tree.add_command(self.cancel)
        await self.tree.sync()

    async def close(self):
        await self.slskd.close()
        await super().close()

    @app_commands.command(name="download", description="Download media via slskd batch (keep one winner, cancel duplicates)")
    async def download(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)
        msg = await interaction.followup.send(f"🔎 Starting search for: `{query}`", wait=True)
        job_id = self.db.create_job(query)

        try:
            sid = (await self.slskd.post("/api/v0/searches", json={
                "searchText": query,
                "filterResponses": False,
                "searchTimeout": self.config.batch_search_timeout_ms,
                "responseLimit": 300,
                "fileLimit": 12000,
            }))['id']

            responses: list[dict[str, Any]] = []
            deadline = time.time() + self.config.batch_response_wait_sec
            while time.time() < deadline:
                responses = await self.slskd.get(f"/api/v0/searches/{sid}/responses")
                if responses:
                    break
                await asyncio.sleep(2)

            if not responses:
                self.db.set_job_state(job_id, "failed", "no responses")
                await msg.edit(content=f"❌ Job `{job_id}`: no responses for `{query}`")
                return

            picks = pick_candidates(responses, query, self.config.batch_max_users)
            if not picks:
                self.db.set_job_state(job_id, "failed", "no matching video candidates")
                await msg.edit(content=f"❌ Job `{job_id}`: no matching video candidates for `{query}`")
                return

            ids: list[tuple[str, str, str, int]] = []
            for score, user, qlen, free, size, fn, f in picks:
                payload = [{"filename": f["filename"], "size": f["size"]}]
                data = await self.slskd.post(f"/api/v0/transfers/downloads/{quote(user, safe='')}", json=payload)
                enq = data.get("enqueued") or []
                if enq:
                    tid = enq[0]["id"]
                    ids.append((user, tid, fn, size))
                    self.db.add_transfer(job_id, user, tid, fn, size)

            if not ids:
                self.db.set_job_state(job_id, "failed", "enqueue failed")
                await msg.edit(content=f"❌ Job `{job_id}`: failed to enqueue any transfer")
                return

            self.db.set_job_state(job_id, "queued")
            await msg.edit(content=f"📥 Job `{job_id}`: enqueued {len(ids)} candidates. Waiting for winner...")

            winner = None
            deadline = time.time() + self.config.batch_start_timeout_sec
            while time.time() < deadline and not winner:
                await asyncio.sleep(3)
                all_dl = await self.slskd.get("/api/v0/transfers/downloads/")
                m = extract_transfer_map(all_dl, {(u, i) for u, i, _, _ in ids})
                for user, tid, fn, size in ids:
                    f = m.get((user, tid))
                    if not f:
                        continue
                    st = f.get("state") or "unknown"
                    bt = int(f.get("bytesTransferred") or 0)
                    self.db.update_transfer(user, tid, st, bt)
                    if bt >= self.config.batch_min_start_bytes or "Completed, Succeeded" in st:
                        winner = (user, tid, fn, bt, st)
                        break

            if winner:
                wuser, wtid, wfn, wbytes, wstate = winner
                self.db.set_winner(job_id, wuser, wtid, wfn)
                # cancel the rest
                for user, tid, fn, size in ids:
                    if (user, tid) == (wuser, wtid):
                        continue
                    await self.slskd.delete(
                        f"/api/v0/transfers/downloads/{quote(user, safe='')}/{tid}",
                        params={"remove": "true"},
                    )

                self.db.set_job_state(job_id, "running", f"winner={wuser}:{wtid}")
                await msg.edit(
                    content=(
                        f"✅ Job `{job_id}` winner selected\n"
                        f"• user: `{wuser}`\n"
                        f"• transfer: `{wtid}`\n"
                        f"• bytes: `{wbytes}`\n"
                        f"• state: `{wstate}`\n"
                        f"• file: `{wfn}`"
                    )
                )
            else:
                self.db.set_job_state(job_id, "stalled", "no winner reached threshold")
                await msg.edit(
                    content=f"⚠️ Job `{job_id}`: no transfer reached min-bytes threshold in time. Left queued for manual review."
                )

        except Exception as e:
            self.db.set_job_state(job_id, "failed", str(e))
            await msg.edit(content=f"❌ Job `{job_id}` failed: `{e}`")

    @app_commands.command(name="status", description="Show latest job or specific job status")
    async def status(self, interaction: discord.Interaction, job_id: int | None = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        job = self.db.job(job_id) if job_id else self.db.latest_job()
        if not job:
            await interaction.followup.send("No jobs yet.", ephemeral=True)
            return
        trs = self.db.transfers(int(job["id"]))
        lines = [
            f"Job `{job['id']}` • state: `{job['state']}`",
            f"query: `{job['query']}`",
        ]
        if job["winner_transfer_id"]:
            lines.append(f"winner: `{job['winner_user']}` `{job['winner_transfer_id']}`")
        if job["notes"]:
            lines.append(f"notes: `{job['notes']}`")
        lines.append("transfers:")
        for t in trs[:10]:
            lines.append(
                f"- `{t['username']}` `{t['transfer_id']}` `{t['state']}` bytes={t['bytes']}"
            )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(name="cancel", description="Cancel all transfers for a job")
    async def cancel(self, interaction: discord.Interaction, job_id: int):
        await interaction.response.defer(thinking=True)
        job = self.db.job(job_id)
        if not job:
            await interaction.followup.send(f"No such job `{job_id}`")
            return
        trs = self.db.transfers(job_id)
        cancelled = 0
        for t in trs:
            try:
                await self.slskd.delete(
                    f"/api/v0/transfers/downloads/{quote(t['username'], safe='')}/{t['transfer_id']}",
                    params={"remove": "true"},
                )
                cancelled += 1
            except Exception:
                pass
        self.db.set_job_state(job_id, "cancelled", f"cancelled={cancelled}")
        await interaction.followup.send(f"🛑 Job `{job_id}` cancelled transfers: `{cancelled}`")


if __name__ == "__main__":
    c = cfg()
    bot = SoulmaneBot(c)
    bot.run(c.discord_token)
