# bot.py
import os
import discord
import random
import datetime
from discord.ext import commands, tasks
from dotenv import load_dotenv
import aiosqlite
import discordSuperUtils
from math import ceil

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

DATABASE_PATH = os.getenv('DATABASE_PATH')

utc = datetime.timezone.utc

# If no tzinfo is given then UTC is assumed.
time = datetime.time(hour=16, minute=0, tzinfo=utc)

intents = discord.Intents.default()
intents.message_content = True

delete_ids = {}

bot = commands.Bot(command_prefix="!qotd-", intents=intents)


@bot.event
async def on_ready():
    print("I'm ready.", bot.user)
    daily_qotd.start()


@bot.check
async def globally_block_dms(ctx):
    return ctx.guild is not None


@tasks.loop(time=time)
async def daily_qotd():
    database = await get_database()
    guilds = await database.select(
        "guilds", ["guild", "channel"], {"schedule": 1}, True
    )
    for guild in guilds:
        message = await get_qotd(guild["guild"])
        channel = bot.get_channel(int(guild["channel"]))
        if channel:
            await channel.send(message)


async def get_database():
    return discordSuperUtils.DatabaseManager.connect(
        await aiosqlite.connect(DATABASE_PATH)
    )


async def filter_questions(questions, max_time):
    filtered_questions = []
    for question in questions:
        if question["last_displayed"] <= max_time:
            filtered_questions.append(question)
    return filtered_questions


async def get_qotd(guild):
    database = await get_database()
    options = await database.select(
        "guilds", ["repeat_interval"], {"guild": guild}
    )
    now = int(datetime.datetime.utcnow().timestamp())
    interval = options["repeat_interval"]
    if not interval:
        max_time = now
    else:
        if interval > 0:
            max_time = (now - interval)
        else:
            max_time = 1

    questions = await database.select(
        "questions", ["ID", "message", "last_displayed"], {
            "guild": guild}, True
    )
    questions = await filter_questions(questions, max_time)
    if len(questions) > 0:
        qotd = random.choice(questions)
        message = qotd["message"]
        ID = qotd["ID"]
        await database.update(
            "questions", {"last_displayed": now}, {"ID": ID},
        )
        return message
    else:
        return "No questions found for this server."

# Taken from discordsuperutils to override the IDs shown per element
def generate_embeds(
    list_to_generate,
    title,
    description,
    fields=25,
    color=0xFF0000,
    string_format="{}",
    footer: str = "",
    display_page_in_footer=False,
    timestamp: datetime = None,
    page_format: str = "(Page {}/{})",
):
    num_of_embeds = ceil((len(list_to_generate) + 1) / fields)
    embeds = []
    for i in range(1, num_of_embeds + 1):
        embeds.append(
            discord.Embed(
                title=title
                if display_page_in_footer
                else f"{title} {page_format.format(i, num_of_embeds)}",
                description=description,
                color=color,
                timestamp=timestamp,
            ).set_footer(
                text=f"{footer} {page_format.format(i, num_of_embeds)}"
                if display_page_in_footer
                else footer
            )
        )

    embed_index = 0
    index = 0
    for ID, message in list_to_generate.items():
        embeds[embed_index].add_field(
            name=f"**{ID}.**", value=string_format.format(message), inline=False
        )

        if (index + 1) % fields == 0:
            embed_index += 1
        index += 1

    return embeds


@bot.command(
        help="Add one or more questions to your server's list, wrapped in quotes and separated by spaces. Adding a question that already exists resets it's last displayed date.",
        brief="Adds new QOTDs."
)
@commands.has_permissions(manage_messages=True)
async def add(ctx, *qotds):
    bad_questions = []
    good_questions = []
    for qotd in qotds:
        if len(qotd.split()) >= 3:
            good_questions.append(qotd)
        else:
            bad_questions.append(qotd)
    comma = r'", "'
    if good_questions:
        database = await get_database()
        good_string = f"\"{comma.join(good_questions)}\""
        await ctx.send(f"Added the question{'s' if len(good_questions) > 1 else ''} {good_string} to the database.")
        for qotd in good_questions:
            tabledata = {"guild": ctx.guild.id, "author": ctx.author.id,
                         "message": qotd, "last_displayed": 0}
            await database.updateorinsert(
                "questions", tabledata, {
                    "guild": ctx.guild.id, "message": qotd}, tabledata
            )
    if bad_questions:
        bad_string = f"\"{comma.join(bad_questions)}\""
        await ctx.send(f"The question{'s' if len(bad_questions) > 1 else ''} {bad_string} were too short. Did you forget quotes?")


@bot.command(
        help="Shows a list of all questions for your server, with their unique ID which you can use to delete them.",
        brief="Lists all QOTDs."
)
@commands.has_permissions(manage_messages=True)
async def list(ctx):
    database = await get_database()
    questions = await database.select(
        "questions", ["ID", "message", "last_displayed"], {
            "guild": ctx.guild.id}, True
    )
    formatted_questions = {
        x['ID']: f"Message: {x['message']}, Last displayed: {datetime.datetime.fromtimestamp(x['last_displayed']) if x['last_displayed'] else 'never'}" for x in questions
    }

    await discordSuperUtils.PageManager(
        ctx,
        generate_embeds(
            formatted_questions,
            title="Question List",
            fields=25,
            description=f"Questions of the Day for {ctx.guild}",
        ),
    ).run()


@bot.command(
        help="Deletes the given question by ID. No confirmation is given, if you make a mistake, add it back :)",
        brief="Deletes a QOTD by ID."
)
@commands.has_permissions(manage_messages=True)
async def delete(ctx, id):
    database = await get_database()
    question = await database.select(
        "questions", ["message"], {"guild": ctx.guild.id, "ID": id}
    )
    if question:
        await database.delete(
            "questions", {"guild": ctx.guild.id, "ID": id}
        )
        await ctx.send(f"Deleted \"{question['message']}\".")
    else:
        await ctx.send("No such message found.")


@bot.command(
        help="Enable daily QOTDs at noon central US time. Be sure to set the channel first.",
        brief="Enables daily QOTDs."
)
@commands.has_permissions(manage_messages=True)
async def enable(ctx):
    database = await get_database()
    tabledata = {"guild": ctx.guild.id, "schedule": 1}
    await database.updateorinsert(
        "guilds", tabledata, {"guild": ctx.guild.id}, tabledata
    )
    await (ctx.send("Enabled question of the day."))


@bot.command(
        help="Disables the daily QOTDs."
)
@commands.has_permissions(manage_messages=True)
async def disable(ctx):
    database = await get_database()
    tabledata = {"guild": ctx.guild.id, "schedule": 0}
    await database.updateorinsert(
        "guilds", tabledata, {"guild": ctx.guild.id}, tabledata
    )
    await (ctx.send("Disabled question of the day."))


@bot.command(
        name='set-channel',
        help="Sets the channel where this command is sent as the designated channel for the daily QOTD, if enabled.",
        brief="Sets QOTD channel."
)
@commands.has_permissions(manage_messages=True)
async def set_channel(ctx):
    database = await get_database()
    tabledata = {"guild": ctx.guild.id, "channel": ctx.message.channel.id}
    await database.updateorinsert(
        "guilds", tabledata, {"guild": ctx.guild.id}, tabledata
    )
    await ctx.send(f"Set this channel {ctx.message.channel} as the target channel for questions-of-the-day.")


@bot.command(
        name='set-repeat',
        help="Sets the minimum time before repeating the same question again. Use 'never' or 'none' for no repetition ever, or a number of days, months, or years. e.g. '2 months'",
        brief="Sets minimum repeat time."
)
@commands.has_permissions(manage_messages=True)
async def set_repeat(ctx, value, unit="days"):
    period = None
    unit = unit.lower()
    if value.isdigit():
        match unit:
            case "days" | "day" | "d":
                period = int(value) * 86400
            case "months" | "month" | "m":
                period = int(value) * 2630000
            case "years" | "year" | "y":
                period = int(value) * 31536000
            case _:
                period = None
    elif value == "never" or value == "none":
        period = -1
    if not period:
        await ctx.send("Invalid time period or unit! Use 'never' or 'none' for no repetition ever, or a number of days, months, or years. e.g. '2 months'")
    else:
        await ctx.send(f"Setting repeat period to {value} {unit}")
        database = await get_database()
        tabledata = {"guild": ctx.guild.id, "repeat_interval": period}
        await database.updateorinsert(
            "guilds", tabledata, {"guild": ctx.guild.id}, tabledata
        )


@bot.command(
        help="Shows a QOTD in this channel. It does mark the question as displayed.",
        brief="Shows a QOTD."
)
@commands.has_permissions(manage_messages=True)
async def get(ctx):
    message = await get_qotd(ctx.guild.id)
    await ctx.send(message)

bot.run(TOKEN)
