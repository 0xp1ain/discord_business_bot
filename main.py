import discord
from discord.ext import commands
from discord import app_commands
import datetime
from database import Database
from typing import List, Dict
import asyncio
import os

class WorkTrackingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database()

    async def setup_hook(self):
        await self.tree.sync()

bot = WorkTrackingBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.setup_hook()

@bot.tree.command(name="출근", description="출근 시간을 기록합니다")
async def clock_in(interaction: discord.Interaction):
    if bot.db.clock_in(str(interaction.user.id)):
        await interaction.response.send_message(
            f"{interaction.user.display_name}님, 출근이 기록되었습니다. 현재 시간: {datetime.datetime.now()}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message("이미 출근 중입니다!", ephemeral=True)

@bot.tree.command(name="퇴근", description="퇴근 시간을 기록합니다")
async def clock_out(interaction: discord.Interaction):
    if bot.db.clock_out(str(interaction.user.id)):
        await interaction.response.send_message(
            f"{interaction.user.display_name}님, 퇴근이 기록되었습니다. 현재 시간: {datetime.datetime.now()}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message("출근 기록이 없습니다!", ephemeral=True)

@bot.tree.command(name="휴식", description="휴식 시작을 기록합니다")
async def break_start(interaction: discord.Interaction):
    if bot.db.start_break(str(interaction.user.id)):
        await interaction.response.send_message("휴식이 시작되었습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("휴식을 시작할 수 없습니다!", ephemeral=True)

@bot.tree.command(name="해제", description="휴식을 종료합니다")
async def break_end(interaction: discord.Interaction):
    if bot.db.end_break(str(interaction.user.id)):
        await interaction.response.send_message("휴식이 종료되었습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("휴식을 종료할 수 없습니다!", ephemeral=True)

@bot.tree.command(name="관리자설정", description="관리자 역할을 설정합니다")
async def set_admin(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("권한이 없습니다!", ephemeral=True)
        return

    if bot.db.add_admin_role(role.id):
        await interaction.response.send_message(f"{role.name}이(가) 관리자로 설정되었습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("이미 관리자로 설정된 역할입니다.", ephemeral=True)

@bot.tree.command(name="결과", description="근무 시간을 확인합니다")
async def view_results(interaction: discord.Interaction):
    if not any(role.id in bot.db.get_admin_roles() for role in interaction.user.roles):
        await interaction.response.send_message("권한이 없습니다!", ephemeral=True)
        return

    guild_members = interaction.guild.members
    results = []
    
    for member in guild_members:
        if member.bot:
            continue
            
        summary = bot.db.get_work_summary(str(member.id))
        if summary["daily_hours"] > 0 or summary["weekly_hours"] > 0:
            results.append(
                f"{member.display_name}:\n"
                f"- 오늘: {summary['daily_hours']:.2f}시간\n"
                f"- 이번 주 누적: {summary['weekly_hours']:.2f}시간"
            )

    if not results:
        await interaction.response.send_message("표시할 근무 기록이 없습니다.", ephemeral=True)
        return

    await interaction.response.send_message("\n\n".join(results), ephemeral=True)

async def members_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    members = interaction.guild.members
    choices = []
    for member in members:
        if not member.bot and (not current or current.lower() in member.display_name.lower()):
            choices.append(app_commands.Choice(name=member.display_name, value=str(member.id)))
    return choices[:25]

meeting_data: Dict[int, Dict[str, str]] = {}

meeting_group = app_commands.Group(name="회의", description="회의 관련 명령어 모음")

@meeting_group.command(name="create", description="새로운 회의를 생성합니다.")
@app_commands.describe(meeting_title="회의 이름")
async def create_meeting(interaction: discord.Interaction, meeting_title: str):
    await interaction.response.defer(ephemeral=True)
    meeting_data[interaction.user.id] = {"title": meeting_title}
    await interaction.followup.send(
        f"회의명 '{meeting_title}'이(가) 설정되었습니다.\n"
        "이제 `/회의 시간 [월/일 시:분]` 형태로 날짜/시간을 설정해 주세요.\n"
        "예) 01/15 04:00",
        ephemeral=True
    )

@meeting_group.command(name="시간", description="회의 날짜/시간을 설정합니다.")
@app_commands.describe(time="예) 01/15 14:00 (24시간제)")
async def set_meeting_time(interaction: discord.Interaction, time: str):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in meeting_data:
        await interaction.followup.send("먼저 `/회의 create [회의명]`을 실행하세요.", ephemeral=True)
        return

    md, hm = time.split()
    month, day = map(int, md.split('/'))
    hour, minute = map(int, hm.split(':'))
    year = datetime.datetime.now().year
    if datetime.datetime.now().month > month:
        year += 1
    meeting_dt = datetime.datetime(year, month, day, hour, minute)
    meeting_str = meeting_dt.strftime('%Y년 %m월 %d일 %H시 %M분')
    meeting_data[interaction.user.id]["time"] = time
    await interaction.followup.send(
        f"회의 시간이 '{meeting_str}'로 설정되었습니다.\n"
        "이제 `/회의 참가자 [@유저1 @유저2 ...]`로 참가자를 지정해 주세요.",
        ephemeral=True
    )

@meeting_group.command(name="참가자", description="회의 참가자를 설정합니다.")
@app_commands.describe(meeting_participants="@유저1 @유저2 ...")
async def set_meeting_participants(interaction: discord.Interaction, meeting_participants: str):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in meeting_data or "time" not in meeting_data[interaction.user.id]:
        await interaction.followup.send(
            "먼저 `/회의 create [회의명]`과 `/회의 시간 [월/일 시:분]`을 차례대로 실행해주세요.",
            ephemeral=True
        )
        return
    meeting_data[interaction.user.id]["participants"] = meeting_participants
    await interaction.followup.send(
        f"참가자가 '{meeting_participants}'로 설정되었습니다.\n"
        "이제 `/회의 setup` 으로 실제 회의를 생성할 수 있습니다.",
        ephemeral=True
    )

@meeting_group.command(name="setup", description="회의를 실제로 셋업합니다.")
async def setup_meeting(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in meeting_data or "time" not in meeting_data[interaction.user.id]:
        await interaction.followup.send(
            "먼저 `/회의 create [회의명]`, `/회의 시간`, `/회의 참가자`를 모두 등록하세요.",
            ephemeral=True
        )
        return

    meeting_title = meeting_data[interaction.user.id]["title"]
    meeting_time = meeting_data[interaction.user.id]["time"]
    meeting_participants = meeting_data[interaction.user.id]["participants"]

    category = await interaction.guild.create_category(f"회의-{meeting_title}")
    text_channel = await category.create_text_channel(f"chat-{meeting_title}")
    voice_channel = await category.create_voice_channel(f"voice-{meeting_title}")

    role = await interaction.guild.create_role(
        name=f"회의-{meeting_title}",
        color=discord.Color.random()
    )

    mentioned_members = []
    for member_id in [m.strip('<@!>') for m in meeting_participants.split()]:
        try:
            member = interaction.guild.get_member(int(member_id))
            if member and not member.bot:
                mentioned_members.append(member)
        except ValueError:
            continue

    if not mentioned_members:
        await interaction.followup.send("유효한 참가자가 없습니다.", ephemeral=True)
        return

    for member in mentioned_members:
        await member.add_roles(role)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        role: discord.PermissionOverwrite(read_messages=True)
    }
    await text_channel.edit(overwrites=overwrites)
    await voice_channel.edit(overwrites=overwrites)

    # 데이터베이스에 저장 가능한 경우
    meeting_id = bot.db.create_meeting(
        meeting_title,
        meeting_time,
        str(interaction.user.id),
        str(text_channel.id),
        str(voice_channel.id),
        str(role.id),
        [str(m.id) for m in mentioned_members]
    )

    # 날짜 파싱
    md, hm = meeting_time.split()
    month, day = map(int, md.split('/'))
    hour, minute = map(int, hm.split(':'))

    year = datetime.datetime.now().year
    # 만약 이번 달보다 이전인 경우 내년으로 설정
    if datetime.datetime.now().month > month:
        year += 1
    meeting_dt = datetime.datetime(year, month, day, hour, minute)
    meeting_str = meeting_dt.strftime('%Y년 %m월 %d일 %H시 %M분')

    # 회의 생성 멘션
    await text_channel.send(
        f"{role.mention} 회의가 생성되었습니다!\n회의 시작 시간: {meeting_str}"
    )

    # 10분 리마인더
    time_until_start = (meeting_dt - datetime.datetime.now()).total_seconds()
    if time_until_start > 600:
        async def remind():
            await asyncio.sleep(time_until_start - 600)
            await text_channel.send(f"{role.mention} 회의 시작 10분 전입니다!")
        asyncio.create_task(remind())

    await interaction.followup.send(
        f"회의 '{meeting_title}'이(가) 생성되었습니다. (ID: {meeting_id})\n"
        f"시간: {meeting_time}, 참가자: {meeting_participants}",
        ephemeral=True
    )

@meeting_group.command(name="end", description="회의를 종료합니다.")
@app_commands.describe(meeting_title="종료할 회의 이름 (채팅방에서 실행 시 자동 인식)")
async def end_meeting(interaction: discord.Interaction, meeting_title: str = None):
    await interaction.response.defer(ephemeral=True)
    if not meeting_title:
        if interaction.channel and interaction.channel.name.startswith("chat-"):
            meeting_title = interaction.channel.name.replace("chat-", "")
        else:
            await interaction.followup.send("회의 이름이 필요합니다.", ephemeral=True)
            return
    
    # 카테고리 및 채널들 삭제
    category_name = f"회의-{meeting_title}"
    category = discord.utils.get(interaction.guild.categories, name=category_name)
    if category:
        for channel in category.channels:
            await channel.delete()
        await category.delete()

    # 역할 삭제
    role_name = f"회의-{meeting_title}"
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if role:
        await role.delete()
    
    # 필요하다면 meeting_data나 DB에서 해당 정보 제거
    # 예) meeting_data.pop(interaction.user.id, None)

    await interaction.followup.send(f"회의 '{meeting_title}'이(가) 종료되었습니다.", ephemeral=True)

bot.tree.add_command(meeting_group)

token = os.environ["TOKEN"]

bot.run(token)