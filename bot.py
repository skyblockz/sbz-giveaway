import asyncio
import datetime
import json
import logging
import random
import re
import time
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
tada_emoji = '\U0001f389'

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
    await bot.wait_until_ready()
    if not bot.loaded_db:
        # bot hasn't loaded DB yet
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
                embed.add_field(name='Hosted By', value=f'<@!{details["host"]}>')
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
            embed = discord.Embed(title=details['prize_name']
                                  )
            embed.add_field(name='Hosted By', value=f'<@!{details["host"]}>')
            if details['requirements']:
                req_ping = [f'<@&{i}>' for i in details['requirements']]
                embed.add_field(name='Requirements (Match one of them)', value=', '.join(req_ping))
            embed.add_field(name='Winner' + ('s' if len(winners) >= 2 else ''), value=', '.join(winners_ping))
            if details['image'] is not None:
                embed.set_image(url=details['image'])
            embed.timestamp = datetime.datetime.utcfromtimestamp(details['created_at'] + details['length'])
            embed.set_footer(text=f'ID: {ga_id}| Ended At')
            cc = bot.get_channel(details['channel_id'])
            mc = await cc.fetch_message(details['message_id'])
            await mc.edit(embed=embed)
            await cc.send(
                f'Giveaway of {details["prize_name"]} (ID:{str(ga_id)}) has been rolled, winners: {" ".join(winners_ping)}\nCongratulations!')


@check_giveaways.error
async def check_giveaways_error_handler(error):
    logging.error('Task check_giveaways has failed')
    traceback.print_exception(type(error), error, error.__traceback__)


class Canceled(Exception):
    pass


@bot.command(name='new', usage='new', description='Launches an interactive session of creating a new giveaway')
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def new_giveaway(ctx):
    def check(message):
        if message.content == 'cancel':
            raise Canceled
        return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

    await ctx.send(
        'Welcome to Interactive Giveaway Creator, please answer some questions before you make a giveaway.\nType `cancel` anytime to terminate the interactive session\n\n1. Where would you like to create the giveaway at?')
    try:
        msg = await bot.wait_for('message', check=check, timeout=240)
        channel = await TextChannelConverter().convert(ctx, msg.content)
        await ctx.send(
            f'Channel will be {channel.mention}\n\n2.How long should the giveaway last for? (suffixes: w-week d-day h-hour, m-minute, s-second)')
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
        host = await MemberConverter().convert(ctx, msg.content)
        await ctx.send(
            f'{host.mention} hosted the giveaway\n\n7. Set any requirements on this giveaway (Type in the role IDs, separate them in space, type none or n if there isn\'t any)')
        msg = await bot.wait_for('message', check=check, timeout=240)
        if msg.content.replace(' ', '').isdigit():
            requirements = [int(i) for i in msg.content.split(' ')]
        else:
            requirements = None
        if requirements is not None:
            req_ping = [f'<@&{i}>' for i in requirements]
        else:
            req_ping = None
        await ctx.send(
            f'Please validate your selections:\n\nCHN {channel.mention}\nLGT `{length}`\nWNC `{winner_count}`\nPZN `{prize_name}`\nIMG `{image}`\nHST {host.mention}\nREQ {", ".join(req_ping) if req_ping is not None else "None"}\n\nType `yes` to start the giveaway',
            allowed_mentions=discord.AllowedMentions.none())
        msg = await bot.wait_for('message', check=check, timeout=240)
        if 'y' not in msg.content:
            raise InterruptedError
        next_id = await db.get_next_id(bot.db)
        creation_time = int(time.time())
        embed = discord.Embed(title=prize_name,
                              colour=discord.Colour.from_rgb(random.randint(0, 255), random.randint(0, 255),
                                                             random.randint(0, 255)))
        embed.add_field(name='Hosted By', value=host.mention)
        if requirements is not None:
            embed.add_field(name='Requirements (Match one of them)', value=', '.join(req_ping))
        embed.add_field(name='Winners', value=str(winner_count))
        if image is not None:
            embed.set_image(url=image)
        embed.timestamp = datetime.datetime.utcfromtimestamp(creation_time + length)
        embed.set_footer(text=f'ID: {next_id}| Ends At')
        sent = await channel.send(embed=embed)
        sent_ctx = await bot.get_context(sent)
        await db.create_giveaway(bot.db, next_id, sent_ctx, length, prize_name, host.id, winner_count, image,
                                 requirements,
                                 creation_time)
        await sent.add_reaction(tada_emoji)
    except asyncio.TimeoutError:
        await ctx.send('Timed out, all inputs have been discarded.')
    except Canceled:
        await ctx.send('Canceled, all inputs have been discarded')
    except BadArgument:
        await ctx.send('Channel or host invalid, terminating interactive session, all inputs have been discarded')
    except InterruptedError:
        await ctx.send('Last validation did not pass, terminating interactive session, all inputs have been discarded')


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    giveaway = await db.search_giveaway(bot.db, 'message_id', payload.message_id)
    if giveaway is None:
        return
    if giveaway['winners'] is not None:
        return
    member = bot.get_guild(payload.guild_id).get_member(payload.user_id)
    res = await db.add_participant(bot.db, giveaway['id'], member)
    msg = await bot.get_guild(payload.guild_id).get_channel(payload.channel_id).fetch_message(payload.message_id)
    msg: discord.Message
    if not res:
        await msg.remove_reaction(tada_emoji, member)
        await member.send(
            f'Your attempt on participating in the giveaway at {msg.jump_url} has been denied, due to the insufficient requirements you meet')
    else:
        await member.send(f'You have successfully participated in the giveaway at {msg.jump_url}')


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    giveaway = await db.search_giveaway(bot.db, 'message_id', payload.message_id)
    if giveaway is None:
        return
    if giveaway['winners'] is not None:
        return
    member = bot.get_guild(payload.guild_id).get_member(payload.user_id)
    await db.remove_participant(bot.db, giveaway['id'], member)
    await member.send(
        f'You have successfully unparticipated the giveaway at https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}')
    return


@bot.command(name='reroll', usage='reroll <giveaway_id>', description='Rerolls the giveaway')
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def reroll(ctx: commands.Context, giveaway_id: int):
    ga = await db.search_giveaway(bot.db, 'id', giveaway_id)
    if ga is None:
        await ctx.send(f'Reroll failed, giveaway ID {giveaway_id} does not exist')
    chn = ctx.guild.get_channel(ga['channel_id'])
    msg = await chn.fetch_message(ga['message_id'])
    new_winners = await db.roll_winner(bot.db, giveaway_id)
    winners_ping = [f'<@!{str(i)}>' for i in new_winners]
    embed = discord.Embed(title=ga['prize_name'] + ' (Rerolled)'
                          )
    embed.add_field(name='Hosted By', value=f'<@!{ga["host"]}>')
    if not ga['requirements']:
        req_ping = [f'<@&{i}>' for i in ga['requirements']]
        embed.add_field(name='Requirements (Match one of them)', value=', '.join(req_ping))
    embed.add_field(name='Winner' + ('s' if len(new_winners) >= 2 else ''), value=', '.join(winners_ping))
    if ga['image'] is not None:
        embed.set_image(url=ga['image'])
    embed.timestamp = datetime.datetime.utcfromtimestamp(ga['created_at'] + ga['length'])
    embed.set_footer(text=f'ID: {giveaway_id}| Ended At')
    await msg.edit(embed=embed)
    await chn.send(
        f'Giveaway of {ga["prize_name"]} (ID:{str(giveaway_id)}) has been rerolled, new winners: {" ".join(winners_ping)}\nCongratulations!')


@bot.command(name='forceaddparticipant', usage='forceaddparticipant <giveaway_id> <member>',
             description='Force adds a pariticpant to the giveaway', aliases=['fadd'])
@commands.is_owner()
async def forceaddpariticpant(ctx, giveaway_id: int, member: discord.Member):
    ga = await db.search_giveaway(bot.db, 'id', giveaway_id)
    if ga is None:
        await ctx.send(f'Force add failed, giveaway ID {giveaway_id} does not exist')
    await db.add_participant(bot.db, giveaway_id, member)


check_giveaways.start()
bot.run(tokens['token'])
