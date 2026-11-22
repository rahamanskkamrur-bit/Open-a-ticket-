import asyncio, datetime, io, json, os, re
import discord
from discord import app_commands
from discord.ext import commands

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
CFG_FILE = "chikago_ticket_config.json"

CATS = {
    "support": ("General Support", "💬", "support", discord.ButtonStyle.primary, discord.Color.blurple(), "Questions about Chikago Crossfire, rules, or general help.", "What do you need help with?"),
    "report": ("Report Player / Exploiter", "🚨", "report", discord.ButtonStyle.danger, discord.Color.red(), "Report hackers, exploiters, RDMers, or toxic players.", "Who are you reporting & what happened?"),
    "appeal": ("Ban / Mute Appeal", "⚖️", "appeal", discord.ButtonStyle.secondary, discord.Color.gold(), "Appeal an in-game or Discord ban, warning, or mute.", "Why were you punished & why should we appeal it?"),
    "bug": ("Bug & Glitch Report", "🐛", "bug", discord.ButtonStyle.secondary, discord.Color.orange(), "Report map glitches, weapon/car bugs, or mobile issues.", "Explain the bug and how to reproduce it:"),
    "shop": ("Gamepass / Shop Issue", "💳", "shop", discord.ButtonStyle.success, discord.Color.green(), "Missing gamepasses, Robux purchases, or VIP claims.", "Which gamepass/item did you buy?"),
    "faction": ("Faction / PD / Partner", "🤝", "faction", discord.ButtonStyle.primary, discord.Color.teal(), "Crew/PD inquiries, content creators, or partnerships.", "Share your faction/server name & details:"),
}

def load_cfgs() -> dict:
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return {}
    return {}

def get_cfg(gid: int) -> dict:
    d = load_cfgs()
    return d.get(str(gid), {"staff_role_id": 0, "category_id": 0, "log_channel_id": 0, "counter": 0})

def set_cfg(gid: int, **kw) -> dict:
    d = load_cfgs(); k = str(gid)
    c = d.get(k, {"staff_role_id": 0, "category_id": 0, "log_channel_id": 0, "counter": 0})
    c.update(kw); d[k] = c
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f: json.dump(d, f, indent=2)
    except Exception: pass
    return c

def is_staff(m: discord.Member) -> bool:
    if not isinstance(m, discord.Member): return False
    if m.guild_permissions.administrator or m.guild_permissions.manage_channels: return True
    rid = get_cfg(m.guild.id).get("staff_role_id", 0)
    return any(r.id == rid for r in m.roles) if rid else False

def parse_topic(topic: str) -> dict:
    t = topic or ""
    u = re.search(r"UserID:(\d+)", t)
    k = re.search(r"Type:([a-z]+)", t)
    rb = re.search(r"Roblox:([^|]+)", t)
    ck = k.group(1) if k and k.group(1) in CATS else "support"
    return {
        "uid": int(u.group(1)) if u else None,
        "type": ck,
        "label": f"{CATS[ck][1]} {CATS[ck][0]}",
        "roblox": rb.group(1).strip() if rb else "Unknown",
    }

async def make_transcript(ch: discord.TextChannel, closer: discord.Member, reason: str, meta: dict) -> tuple[bytes, int]:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "=" * 64,
        "          🔥 CHIKAGO CROSSFIRE — TICKET TRANSCRIPT",
        "=" * 64,
        f"Server   : {ch.guild.name}",
        f"Channel  : #{ch.name} | Category: {meta['label']}",
        f"PlayerID : {meta['uid']} | Roblox: {meta['roblox']}",
        f"ClosedBy : {closer} ({closer.id})",
        f"Reason   : {reason}",
        f"ClosedAt : {now}",
        "=" * 64, "",
    ]
    cnt = 0
    try:
        async for m in ch.history(limit=1000, oldest_first=True):
            cnt += 1
            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append(f"[{ts}] {m.author.display_name} (@{m.author.name}){' [BOT]' if m.author.bot else ''}:")
            if m.content:
                lines.extend(f"    {ln}" for ln in m.content.splitlines())
            for e in m.embeds:
                if e.title: lines.append(f"    [Embed] {e.title}")
                if e.description: lines.append(f"    | {e.description.replace(chr(10), ' ')}")
                for fl in e.fields: lines.append(f"    • {fl.name}: {str(fl.value).replace(chr(10), ' ')}")
            for a in m.attachments:
                lines.append(f"    [Attachment: {a.filename}] {a.url}")
            lines.append("")
    except Exception as e:
        lines.append(f"[History Error: {e}]")
    lines.append(f"=== End of Transcript ({cnt} messages) ===")
    return "\n".join(lines).encode("utf-8"), cnt

class IntakeModal(discord.ui.Modal):
    def __init__(self, key: str):
        lbl, em, *_ = CATS[key]
        super().__init__(title=f"{em} {lbl}"[:45])
        self.key = key
        self.rblx = discord.ui.TextInput(label="Your Roblox Username", placeholder="e.g. CrossfirePlayer123", required=True, max_length=50)
        self.info = discord.ui.TextInput(label="Details", placeholder=CATS[key][6][:100], style=discord.TextStyle.paragraph, required=True, max_length=900)
        self.proof = discord.ui.TextInput(label="Proof / Extra Info (Optional)", placeholder="Screenshot/clip link or player name...", required=False, max_length=250)
        for x in (self.rblx, self.info, self.proof): self.add_item(x)

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        g, u = i.guild, i.user
        lbl, em, pref, _, col, _, _ = CATS[self.key]
        cfg = get_cfg(g.id)
        for ch in g.text_channels:
            if ch.topic and f"UserID:{u.id}" in ch.topic and f"Type:{self.key}" in ch.topic:
                return await i.followup.send(f"⚠️ You already have an open **{lbl}** ticket: {ch.mention}", ephemeral=True)

        ow = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            u: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True, read_message_history=True, attach_files=True, embed_links=True),
        }
        s_role = g.get_role(cfg.get("staff_role_id", 0))
        ping = ""
        if s_role:
            ow[s_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
            ping = s_role.mention

        cat = g.get_channel(cfg.get("category_id", 0))
        if not isinstance(cat, discord.CategoryChannel): cat = None
        num = int(cfg.get("counter", 0)) + 1
        set_cfg(g.id, counter=num)
        sname = re.sub(r"[^a-z0-9]", "", u.name.lower())[:12] or "player"
        rblx = self.rblx.value.replace("|", "").strip()

        try:
            tch = await g.create_text_channel(f"{pref}-{num:04d}-{sname}", category=cat, overwrites=ow, topic=f"ChikagoTicket | Type:{self.key} | UserID:{u.id} | Roblox:{rblx}")
        except discord.Forbidden:
            return await i.followup.send("❌ I need **Manage Channels** permission!", ephemeral=True)

        emb = discord.Embed(title=f"{em} Chikago Crossfire — {lbl} (#{num:04d})", description=f"Welcome {u.mention}! Staff will help you shortly. Feel free to drop clips or screenshots here.", color=col, timestamp=datetime.datetime.now(datetime.timezone.utc))
        emb.add_field(name="👤 Player", value=f"{u.mention} (`{u.id}`)", inline=True)
        emb.add_field(name="🎮 Roblox User", value=f"`{rblx}`", inline=True)
        emb.add_field(name="🙋 Claimed By", value="*Unclaimed*", inline=True)
        emb.add_field(name="📝 Details", value=self.info.value, inline=False)
        if self.proof.value.strip(): emb.add_field(name="📎 Proof", value=self.proof.value.strip(), inline=False)
        emb.set_footer(text="When closed, a full transcript will be DMed to you automatically.")
        await tch.send(content=f"{u.mention} {ping}".strip(), embed=emb, view=TicketCtrlView())
        await i.followup.send(f"✅ Opened your **{lbl}** ticket: {tch.mention}", ephemeral=True)

class CloseModal(discord.ui.Modal, title="🔒 Close Ticket & DM Transcript"):
    reason = discord.ui.TextInput(label="Close Reason / Resolution", default="Resolved", required=True, max_length=200)

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer()
        ch, g = i.channel, i.guild
        meta = parse_topic(ch.topic)
        rsn = self.reason.value.strip() or "Resolved"
        await i.followup.send("📄 Generating transcript & DMing the player... Closing in **5 seconds**.")

        raw, cnt = await make_transcript(ch, i.user, rsn, meta)
        fname = f"transcript-{ch.name}.txt"
        now = datetime.datetime.now(datetime.timezone.utc)

        dm_emb = discord.Embed(title="📄 Chikago Crossfire — Ticket Transcript", description=f"Your ticket **`#{ch.name}`** in **{g.name}** was closed. Your full transcript is attached above.", color=discord.Color.dark_teal(), timestamp=now)
        dm_emb.add_field(name="📂 Category", value=meta["label"], inline=True)
        dm_emb.add_field(name="🎮 Roblox User", value=f"`{meta['roblox']}`", inline=True)
        dm_emb.add_field(name="💬 Messages", value=f"`{cnt}`", inline=True)
        dm_emb.add_field(name="🔒 Closed By", value=f"{i.user.mention} (`{i.user.display_name}`)", inline=True)
        dm_emb.add_field(name="📝 Resolution", value=rsn, inline=False)

        dm_stat = "⚠️ Unknown player ID"
        uid = meta["uid"]
        if uid:
            opener = g.get_member(uid)
            if not opener:
                try: opener = await i.client.fetch_user(uid)
                except Exception: opener = None
            if opener:
                try:
                    await opener.send(embed=dm_emb, file=discord.File(io.BytesIO(raw), filename=fname))
                    dm_stat = f"✅ DMed to {opener.mention}"
                except discord.Forbidden:
                    dm_stat = f"⚠️ {opener.mention} has DMs off"
                except Exception as e:
                    dm_stat = f"⚠️ DM error: `{type(e).__name__}`"

        log_ch = g.get_channel(get_cfg(g.id).get("log_channel_id", 0))
        if isinstance(log_ch, discord.TextChannel):
            le = discord.Embed(title=f"🗂️ Transcript Archived — #{ch.name}", description=f"**Player:** <@{uid}> (`{uid}`)\n**DM Status:** {dm_stat}", color=discord.Color.blurple(), timestamp=now)
            le.add_field(name="📂 Category", value=meta["label"], inline=True)
            le.add_field(name="🎮 Roblox", value=f"`{meta['roblox']}`", inline=True)
            le.add_field(name="💬 Messages", value=f"`{cnt}`", inline=True)
            le.add_field(name="🔒 Closed By", value=i.user.mention, inline=True)
            le.add_field(name="📝 Reason", value=rsn, inline=False)
            try: await log_ch.send(embed=le, file=discord.File(io.BytesIO(raw), filename=fname))
            except Exception: pass

        await asyncio.sleep(5)
        try: await ch.delete(reason=f"Closed by {i.user}: {rsn}")
        except Exception: pass

class TicketCtrlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, emoji="🙋", custom_id="ccf:claim")
    async def claim_b(self, i: discord.Interaction, b: discord.ui.Button):
        if not is_staff(i.user): return await i.response.send_message("❌ Staff only.", ephemeral=True)
        b.disabled = True; b.label = f"Claimed by {i.user.display_name[:20]}"; b.style = discord.ButtonStyle.secondary
        emb = i.message.embeds[0] if i.message.embeds else None
        if emb and len(emb.fields) >= 3:
            emb.set_field_at(2, name="🙋 Claimed By", value=i.user.mention, inline=True)
            await i.response.edit_message(embed=emb, view=self)
        else:
            await i.response.edit_message(view=self)
        await i.channel.send(f"✅ {i.user.mention} has claimed this ticket!")

    @discord.ui.button(label="Close & DM Transcript", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ccf:close")
    async def close_b(self, i: discord.Interaction, b: discord.ui.Button):
        if not is_staff(i.user) and i.user.id != parse_topic(i.channel.topic)["uid"]:
            return await i.response.send_message("❌ Only Staff or the ticket owner can close this.", ephemeral=True)
        await i.response.send_modal(CloseModal())

class TicketPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="General Support", style=discord.ButtonStyle.primary, emoji="💬", custom_id="ccf_p:support", row=0)
    async def b1(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(IntakeModal("support"))

    @discord.ui.button(label="Report Player / Exploiter", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="ccf_p:report", row=0)
    async def b2(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(IntakeModal("report"))

    @discord.ui.button(label="Ban / Mute Appeal", style=discord.ButtonStyle.secondary, emoji="⚖️", custom_id="ccf_p:appeal", row=0)
    async def b3(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(IntakeModal("appeal"))

    @discord.ui.button(label="Bug & Glitch Report", style=discord.ButtonStyle.secondary, emoji="🐛", custom_id="ccf_p:bug", row=1)
    async def b4(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(IntakeModal("bug"))

    @discord.ui.button(label="Gamepass / Shop Issue", style=discord.ButtonStyle.success, emoji="💳", custom_id="ccf_p:shop", row=1)
    async def b5(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(IntakeModal("shop"))

    @discord.ui.button(label="Faction / PD / Partner", style=discord.ButtonStyle.primary, emoji="🤝", custom_id="ccf_p:faction", row=1)
    async def b6(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(IntakeModal("faction"))

class ChikagoBot(commands.Bot):
    def __init__(self, msg_intent: bool = True):
        intents = discord.Intents.default(); intents.message_content = msg_intent
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        self.add_view(TicketPanelView()); self.add_view(TicketCtrlView())
        await self.tree.sync()

    async def on_ready(self):
        print(f"✅ Chikago Crossfire Ticket Bot ONLINE as {self.user}")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Chikago Crossfire Support 🎫"))

def reg_cmds(bot: ChikagoBot):
    @bot.tree.command(name="ticket_setup", description="Set Staff Role, Ticket Category, and Transcript Log Channel")
    async def c_setup(i: discord.Interaction, staff_role: discord.Role, ticket_category: discord.CategoryChannel, transcript_log_channel: discord.TextChannel):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("❌ Admins only.", ephemeral=True)
        set_cfg(i.guild.id, staff_role_id=staff_role.id, category_id=ticket_category.id, log_channel_id=transcript_log_channel.id)
        await i.response.send_message(f"✅ Saved!\n🛡️ Staff: {staff_role.mention}\n📁 Category: `{ticket_category.name}`\n🗂️ Logs: {transcript_log_channel.mention}\n👉 Run **`/ticket_panel`** next!", ephemeral=True)

    @bot.tree.command(name="ticket_panel", description="Post the Chikago Crossfire 6-button Ticket Panel")
    async def c_panel(i: discord.Interaction):
        if not is_staff(i.user): return await i.response.send_message("❌ Staff only.", ephemeral=True)
        desc = "\n".join(f"{v[1]} **{v[0]}** — {v[5]}" for v in CATS.values())
        emb = discord.Embed(title="🔥 CHIKAGO CROSSFIRE — Support & Ticket Center", description=f"Select a category below to open a private ticket:\n\n{desc}\n\n📄 *Keep DMs open to receive your Ticket Transcript automatically!*", color=discord.Color.from_rgb(220, 53, 69))
        emb.set_footer(text="Chikago Crossfire Support")
        await i.channel.send(embed=emb, view=TicketPanelView())
        await i.response.send_message("✅ Ticket panel posted!", ephemeral=True)

    @bot.tree.command(name="ticket_add", description="Add a member to this ticket")
    async def c_add(i: discord.Interaction, member: discord.Member):
        if not is_staff(i.user) or not (i.channel.topic and "ChikagoTicket" in i.channel.topic):
            return await i.response.send_message("❌ Staff only, inside a ticket channel.", ephemeral=True)
        await i.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        await i.response.send_message(f"➕ Added {member.mention} to this ticket.")

    @bot.tree.command(name="ticket_remove", description="Remove a member from this ticket")
    async def c_rem(i: discord.Interaction, member: discord.Member):
        if not is_staff(i.user) or not (i.channel.topic and "ChikagoTicket" in i.channel.topic):
            return await i.response.send_message("❌ Staff only, inside a ticket channel.", ephemeral=True)
        await i.channel.set_permissions(member, overwrite=None)
        await i.response.send_message(f"➖ Removed {member.mention} from this ticket.")

async def main():
    if not BOT_TOKEN:
        print("❌ Missing BOT_TOKEN! Add BOT_TOKEN in your host's Startup/Environment tab.")
        while True: await asyncio.sleep(3600)
    bot = ChikagoBot(True); reg_cmds(bot)
    try:
        await bot.start(BOT_TOKEN)
    except discord.PrivilegedIntentsRequired:
        await bot.close(); bot = ChikagoBot(False); reg_cmds(bot); await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
