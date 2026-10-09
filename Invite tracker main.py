
import os
import sqlite3
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()





TOKEN = os.getenv("TOKEN")

# HIER DIE ID DEINES LOG-KANALS EINTRAGEN
INVITE_LOG_CHANNEL_ID = #(klammer und "#" die logchannel ID für den Tracker einfügen)

# Neue Datenbank
DB_FILE = "invite_tracker.db"

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN fehlt. Setze zuerst die Bot-Token-Umgebungsvariable."
    )


intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


invite_cache = defaultdict(dict)


def create_table():
    with sqlite3.connect(DB_FILE) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS invite_joins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                inviter_id INTEGER,
                member_id INTEGER NOT NULL,
                invite_code TEXT,
                joined_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_invites_guild_inviter
            ON invite_joins (guild_id, inviter_id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_invites_guild_member
            ON invite_joins (guild_id, member_id)
        """)

    print("[DB] Datenbank bereit.")


def save_join(
    guild_id: int,
    member_id: int,
    inviter_id: Optional[int],
    invite_code: Optional[str]
):
    with sqlite3.connect(DB_FILE) as db:
        db.execute("""
            INSERT INTO invite_joins (
                guild_id,
                inviter_id,
                member_id,
                invite_code,
                joined_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            guild_id,
            inviter_id,
            member_id,
            invite_code,
            datetime.now(timezone.utc).isoformat()
        ))


def get_invite_count(guild_id: int, inviter_id: int) -> int:
    with sqlite3.connect(DB_FILE) as db:
        result = db.execute("""
            SELECT COUNT(*)
            FROM invite_joins
            WHERE guild_id = ?
              AND inviter_id = ?
        """, (guild_id, inviter_id)).fetchone()

    return result[0] if result else 0


def get_member_invite_info(guild_id: int, member_id: int):
    with sqlite3.connect(DB_FILE) as db:
        return db.execute("""
            SELECT inviter_id, invite_code, joined_at
            FROM invite_joins
            WHERE guild_id = ?
              AND member_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (guild_id, member_id)).fetchone()


def get_leaderboard(guild_id: int, limit: int = 10):
    with sqlite3.connect(DB_FILE) as db:
        return db.execute("""
            SELECT inviter_id, COUNT(*) AS total
            FROM invite_joins
            WHERE guild_id = ?
              AND inviter_id IS NOT NULL
            GROUP BY inviter_id
            ORDER BY total DESC
            LIMIT ?
        """, (guild_id, limit)).fetchall()

async def refresh_invites(guild: discord.Guild):
    try:
        invites = await guild.invites()

        invite_cache[guild.id] = {
            invite.code: {
                "uses": invite.uses if invite.uses is not None else 0,
                "inviter_id": (
                    invite.inviter.id if invite.inviter else None
                )
            }
            for invite in invites
        }

        print(
            f"[CACHE] {guild.name}: "
            f"{len(invites)} Einladungen geladen."
        )

        for code, data in invite_cache[guild.id].items():
            print(
                f"[CACHE TEST] Code={code} "
                f"Uses={data['uses']} "
                f"Inviter-ID={data['inviter_id']}"
            )

    except discord.Forbidden:
        print(
            f"[FEHLER] Keine Berechtigung, Einladungen auf "
            f"{guild.name} abzurufen. Benötigt wird "
            f"'Server verwalten'."
        )

    except discord.HTTPException as error:
        print(f"[FEHLER] Einladungen konnten nicht geladen werden: {error}")

async def send_log(guild: discord.Guild, embed: discord.Embed):
    channel = guild.get_channel(INVITE_LOG_CHANNEL_ID)

    if channel is None:
        try:
            channel = await bot.fetch_channel(INVITE_LOG_CHANNEL_ID)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):
            print(
                "[FEHLER] Log-Kanal nicht gefunden oder nicht erreichbar. "
                "Prüfe INVITE_LOG_CHANNEL_ID."
            )
            return

    if not hasattr(channel, "send"):
        print("[FEHLER] Der konfigurierte Kanal kann keine Nachrichten senden.")
        return

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as error:
        print(f"[FEHLER] Log konnte nicht gesendet werden: {error}")


@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")
    print(f"Bot-ID: {bot.user.id}")

    for guild in bot.guilds:
        await refresh_invites(guild)

    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} Slash-Commands geladen.")
    except discord.HTTPException as error:
        print(f"[FEHLER] Slash-Commands konnten nicht synchronisiert werden: {error}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    await refresh_invites(guild)


@bot.event
async def on_invite_create(invite: discord.Invite):
    guild = invite.guild

    if guild is None:
        return

    invite_cache[guild.id][invite.code] = {
        "uses": invite.uses if invite.uses is not None else 0,
        "inviter_id": invite.inviter.id if invite.inviter else None
    }

    creator = invite.inviter.mention if invite.inviter else "Unbekannt"

    channel_text = (
        invite.channel.mention
        if invite.channel
        else "Unbekannt"
    )

    if invite.max_age == 0:
        expires_text = "Läuft nie ab"
    else:
        expires_text = f"In {invite.max_age // 3600} Stunden"

    max_uses_text = (
        "Unbegrenzt"
        if invite.max_uses == 0
        else str(invite.max_uses)
    )

    uses_now = invite.uses if invite.uses is not None else 0

    embed = discord.Embed(
        title="🔗 Neuer Einladungslink erstellt",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="Erstellt von",
        value=creator,
        inline=True
    )
    embed.add_field(
        name="Kanal",
        value=channel_text,
        inline=True
    )
    embed.add_field(
        name="Einladungslink",
        value=f"https://discord.gg/{invite.code}",
        inline=False
    )
    embed.add_field(
        name="Maximale Nutzungen",
        value=max_uses_text,
        inline=True
    )
    embed.add_field(
        name="Bisher verwendet",
        value=str(uses_now),
        inline=True
    )
    embed.add_field(
        name="Gültigkeit",
        value=expires_text,
        inline=True
    )

    await send_log(guild, embed)

    print(
        f"[INVITE CREATE] Link {invite.code} erstellt "
        f"von {invite.inviter}"
    )


@bot.event
async def on_invite_delete(invite: discord.Invite):
    guild = invite.guild

    if guild is None:
        return

    invite_cache[guild.id].pop(invite.code, None)

    embed = discord.Embed(
        title="🗑️ Einladungslink gelöscht",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="Einladungslink",
        value=f"https://discord.gg/{invite.code}",
        inline=False
    )
    embed.add_field(
        name="Ersteller",
        value=invite.inviter.mention if invite.inviter else "Unbekannt",
        inline=True
    )

    await send_log(guild, embed)

    print(f"[INVITE DELETE] Link {invite.code} gelöscht.")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    print(f"[JOIN] {member} ist dem Server {guild.name} beigetreten.")

    old_invites = invite_cache.get(guild.id, {}).copy()
    used_invite = None

    try:
        current_invites = await guild.invites()
        increased = []

        for invite in current_invites:
            old_data = old_invites.get(invite.code)

            old_uses = (
                old_data["uses"]
                if old_data is not None
                else 0
            )

            new_uses = (
                invite.uses
                if invite.uses is not None
                else 0
            )

            print(
                f"[INVITE DEBUG] Code={invite.code} "
                f"Vorher={old_uses} Jetzt={new_uses} "
                f"Ersteller={invite.inviter}"
            )

            if new_uses > old_uses:
                increased.append(invite)

        if len(increased) == 1:
            used_invite = increased[0]

        # Cache immer mit den neuesten Nutzungszahlen aktualisieren
        invite_cache[guild.id] = {
            invite.code: {
                "uses": invite.uses if invite.uses is not None else 0,
                "inviter_id": (
                    invite.inviter.id if invite.inviter else None
                )
            }
            for invite in current_invites
        }

    except discord.Forbidden:
        print("[FEHLER] Keine Berechtigung, Einladungen abzurufen.")

    except discord.HTTPException as error:
        print(f"[FEHLER] Einladungen konnten nicht abgerufen werden: {error}")

    inviter = used_invite.inviter if used_invite else None
    invite_code = used_invite.code if used_invite else None

    try:
        save_join(
            guild.id,
            member.id,
            inviter.id if inviter else None,
            invite_code
        )
    except sqlite3.Error as error:
        print(f"[DB FEHLER] Beitritt konnte nicht gespeichert werden: {error}")

    # Haupt-Log zum Beitritt
    embed = discord.Embed(
        title="📥 Neues Mitglied",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(
        name="Mitglied",
        value=f"{member.mention}\n`{member}`",
        inline=True
    )
    embed.add_field(
        name="Servermitglieder",
        value=str(guild.member_count or len(guild.members)),
        inline=True
    )
    embed.add_field(
        name="Eingeladen von",
        value=inviter.mention if inviter else "Unbekannt",
        inline=True
    )
    embed.add_field(
        name="Einladungslink",
        value=(
            f"https://discord.gg/{invite_code}"
            if invite_code
            else "Nicht eindeutig erkannt"
        ),
        inline=False
    )

    await send_log(guild, embed)

    # Separates Nutzungs-Log
    if used_invite:
        uses_now = (
            used_invite.uses
            if used_invite.uses is not None
            else 0
        )

        usage_embed = discord.Embed(
            title="📈 Einladungslink verwendet",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        usage_embed.add_field(
            name="Beigetretenes Mitglied",
            value=member.mention,
            inline=True
        )
        usage_embed.add_field(
            name="Eingeladen von",
            value=inviter.mention if inviter else "Unbekannt",
            inline=True
        )
        usage_embed.add_field(
            name="Einladungslink",
            value=f"https://discord.gg/{used_invite.code}",
            inline=False
        )
        usage_embed.add_field(
            name="Verwendungen laut Discord",
            value=str(uses_now),
            inline=True
        )

        await send_log(guild, usage_embed)

        print(
            f"[JOIN] Einladung erkannt: {used_invite.code} "
            f"von {inviter}; Nutzungen: {uses_now}"
        )
    else:
        print(
            "[JOIN] Einladender nicht eindeutig erkannt. "
            "Der Beitritt wurde trotzdem gespeichert."
        )




@bot.tree.command(
    name="invites",
    description="Zeigt die Anzahl deiner Einladungen."
)
@app_commands.describe(user="Optional ein anderes Mitglied auswählen")
async def invites(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Dieser Befehl funktioniert nur auf einem Server.",
            ephemeral=True
        )
        return

    target = user or interaction.user
    count = get_invite_count(interaction.guild.id, target.id)

    embed = discord.Embed(
        title="📨 Einladungen",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(
        name="Mitglied",
        value=target.mention,
        inline=True
    )
    embed.add_field(
        name="Erfolgreiche Einladungen",
        value=str(count),
        inline=True
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="inviteinfo",
    description="Zeigt die Einladungsinformationen eines Mitglieds."
)
@app_commands.describe(member="Mitglied auswählen")
async def inviteinfo(
    interaction: discord.Interaction,
    member: discord.Member
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Dieser Befehl funktioniert nur auf einem Server.",
            ephemeral=True
        )
        return

    info = get_member_invite_info(interaction.guild.id, member.id)

    embed = discord.Embed(
        title="🔎 Einladungsinformationen",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Mitglied",
        value=member.mention,
        inline=False
    )

    if info is None:
        embed.description = "Für dieses Mitglied wurde kein Beitritt gespeichert."
    else:
        inviter_id, invite_code, joined_at = info

        embed.add_field(
            name="Eingeladen von",
            value=(
                f"<@{inviter_id}>"
                if inviter_id is not None
                else "Unbekannt"
            ),
            inline=True
        )

        embed.add_field(
            name="Einladungslink",
            value=(
                f"https://discord.gg/{invite_code}"
                if invite_code
                else "Nicht eindeutig erkannt"
            ),
            inline=False
        )

        embed.add_field(
            name="Beitrittszeitpunkt (UTC)",
            value=joined_at,
            inline=False
        )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="leaderboard",
    description="Zeigt die Mitglieder mit den meisten Einladungen."
)
async def leaderboard(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Dieser Befehl funktioniert nur auf einem Server.",
            ephemeral=True
        )
        return

    rows = get_leaderboard(interaction.guild.id, 10)

    embed = discord.Embed(
        title="🏆 Invite-Leaderboard",
        color=discord.Color.gold()
    )

    if not rows:
        embed.description = (
            "Bisher wurden keine Einladungen eindeutig zugeordnet."
        )
    else:
        lines = []

        for position, (user_id, count) in enumerate(rows, start=1):
            lines.append(
                f"**{position}.** <@{user_id}> — **{count}** Einladungen"
            )

        embed.description = "\n".join(lines)

    await interaction.response.send_message(embed=embed)


create_table()
bot.run(os.getenv("TOKEN"))