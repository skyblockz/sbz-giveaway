import asyncio
import datetime
import json
import logging
import re
import traceback

import asyncpg
import discord
import humanize
from discord.ext import commands, tasks
from discord.ext.commands import TextChannelConverter, BadArgument, MemberConverter

import db


class SBZGiveawayBot(commands.Bot):
    def __init__(self, **options):
        super().__init__(**options)
        self.db = None
        self.loaded_db = False


intents = discord.Intents.all()
logging.basicConfig(level=logging.INFO)
bot = SBZGiveawayBot(command_prefix='g$', intents=intents)
bot.load_extension('jishaku')

with open('token.json', 'r') as f:
    tokens = json.loads(f.read())


def convert_time(raw):
    """
    Convert human time (eg. 10h10m) into seconds

    :param raw: Human time
    :return: Seconds
    """
    res = re.split(r'(\d+)', raw)
    res.pop(0)
    total_time = 0
    current_working = 0
    time_suffixes = {'w': 604800, 'd': 86400, 'h': 3600, 'm': 60, 's': 1}
    for i in res:
        if i.isdigit():
            current_working = i
        else:
            total_time += int(current_working) * time_suffixes[i]
            current_working = 0
    return total_time


@bot.event
async def on_connect():
    if not bot.loaded_db:
        logging.info('LOADED DATABASE')
        bot.db = await asyncpg.create_pool(**tokens['pgsql'])
        await db.ensure_database_validity(bot.db)
        bot.loaded_db = True
    print('Connected')


@bot.event
async def on_ready():
    print('Ready')


@tasks.loop(seconds=1)
async def check_giveaways():
    if not bot.loaded_db:
        # bot hasnt loaded DB yet
        return
    need_rolling = await db.get_need_rolling_giveaways(bot.db)
    if len(need_rolling) == 0:
        pass
    else:
        for ga_id in need_rolling:
            try:
                winners = await db.roll_winner(bot.db, ga_id)
            except db.NoParticipants:
                details = await db.get_info_of_giveaway(bot.db, ga_id)
                embed = discord.Embed(title=details['prize_name'],
                                      description='No one has joined the giveaway, thus the roll has been canceled',
                                      colour=discord.Colour.dark_red())
                embed.add_field(name='Hosted By', value=details['host'])
                if details['image'] is not None:
                    embed.set_image(url=details['image'])
                embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
                embed.set_footer(text=f'ID: {ga_id}| Ended At')
                cc = bot.get_channel(details['channel_id'])
                mc = await cc.fetch_message(details['message_id'])
                await mc.edit(embed=embed)
                await cc.send(
                    f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been canceled, due to no participants in the giveaway')
                continue
            except db.NotEnoughParticipants:
                details = await db.get_info_of_giveaway(bot.db, ga_id)
                embed = discord.Embed(title=details['prize_name'],
                                      description=f'Not enough people joined the giveaway (only {len(details["participants"])}), thus the roll has been canceled',
                                      colour=discord.Colour.dark_red())
                embed.add_field(name='Hosted By', value=details['host'])
                if details['image'] is not None:
                    embed.set_image(url=details['image'])
                embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
                embed.set_footer(text=f'ID: {ga_id}| Ended At')
                cc = bot.get_channel(details['channel_id'])
                mc = await cc.fetch_message(details['message_id'])
                await mc.edit(embed=embed)
                await cc.send(
                    f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been canceled, due to not enough people joined the giveaway (only {len(details["participants"])})')
                continue
            details = await db.get_info_of_giveaway(bot.db, ga_id)
            winners_ping = [f'<@!{i}>' for i in details['winners']]
            embed = discord.Embed(title=details['prize_name'],
                                  description=f'Winner{"s" if details["winner_count"] > 1 else ""}: {" ".join(winners_ping)}'
                                  )
            embed.add_field(name='Hosted By', value=details['host'])
            if details['image'] is not None:
                embed.set_image(url=details['image'])
            embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
            embed.set_footer(text=f'ID: {ga_id}| Ended At')
            cc = bot.get_channel(details['channel_id'])
            mc = await cc.fetch_message(details['message_id'])
            await mc.edit(embed=embed)
            await cc.send(
                f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been rolled, winners: {" ".join(winners_ping)}')


@check_giveaways.error
async def check_giveaways_error_handler(error):
    logging.error('Task check_giveaways has failed')
    traceback.print_exception(type(error), error, error.__traceback__)


class Canceled(Exception):
    pass


@bot.command(name='new', usage='new', description='Launches an interactive session of creating a new giveaway')
async def new_giveaway(ctx):
    def check(message):
        if message.content == 'cancel':
            raise Canceled
        return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

    await ctx.send(
        'Welcome to Interactive Giveaway Creator, please answer some questions before you make a giveaway.\nType `cancel` anytime to terminate the interactive session\n\n1. Where would you like to create the giveaway at?')
    try:
        msg = await bot.wait_for('message', check=check, timeout=240)
        channel_id = (await TextChannelConverter().convert(ctx, msg.content)).id
        await ctx.send(
            f'Channel will be <#{str(channel_id)}>\n\n2.How long should the giveaway last for? (suffixes: w-week d-day h-hour, m-minute, s-second)')
        msg = await bot.wait_for('message', check=check, timeout=240)
        length = convert_time(msg.content)
        await ctx.send(
            f'It will last for {humanize.naturaltime(length, future=True).rstrip(" from now")}\n\n3. How many winners should there be?')
        msg = await bot.wait_for('message', check=check, timeout=240)
        winner_count = int(msg.content)
        await ctx.send(
            f'There will be {str(winner_count)} winner{"s" if winner_count > 1 else ""}\n\n4. What should the prize be?')
        msg = await bot.wait_for('message', check=check, timeout=240)
        prize_name = msg.content
        await ctx.send(
            f'The prize will be {prize_name}\n\n5. Any showcase images for it? (Only one allowed) (Please post a link to the file or upload it as an attachment) (Type none or n if there isn\'t any)')
        msg = await bot.wait_for('message', check=check, timeout=240)
        if msg.content.lower() == 'none' or msg.content.lower() == 'n':
            image = None
        else:
            if len(msg.attachments) <= 0:
                image = msg.content
            else:
                image = msg.attachments[0].url
        await ctx.send(
            f'Image URL will be {image}\n\n6. Who donated for the giveaway? (You can enter their user ID / name#1234 or ping them)')
        msg = await bot.wait_for('message', check=check, timeout=240)
        host = (await MemberConverter().convert(ctx, msg.content)).id
        await ctx.send(
            f'<@!{host}> hosted the giveaway\n\n7. Set any requirements on this giveaway (Type in the role IDs, separate them in space, type none or n if there isn\'t any)')
        msg = await bot.wait_for('message', check=check, timeout=240)
        if msg.content.replace(' ', '').isdigit():
            requirements = [int(i) for i in msg.content.split(' ')]
        else:
            requirements = None
        req_ping = [f'<@&{i}>' for i in requirements]
        await ctx.send(
            f'Please validate your selections:\n\nCID `{channel_id}`\nLGT `{length}`\nWNC `{winner_count}`\nPZN `{prize_name}`\nIMG `{image}`\nHST `{host}`\nREQ {", ".join(req_ping)}\n\nType `yes` to start the giveaway', allowed_mentions=discord.AllowedMentions.none())
        msg = await bot.wait_for('message', check=check, timeout=240)
        if 'y' not in msg.content:
            raise InterruptedError
        await ctx.send('it should create smth now')
    except asyncio.TimeoutError:
        await ctx.send('Timed out, all inputs have been discarded.')
    except Canceled:
        await ctx.send('Canceled, all inputs have been discarded')
    except BadArgument:
        await ctx.send('Channel or host invalid, terminating interactive session, all inputs have been discarded')
    except InterruptedError:
        await ctx.send('Last validation did not pass, terminating interactive session, all inputs have been discarded')


check_giveaways.start()
bot.run(tokens['token'])
