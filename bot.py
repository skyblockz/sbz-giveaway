import asyncio
import datetime
import json
import logging
import random
import re
import time
import traceback
import typing

import aiohttp
import asyncpg
import discord
import git
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
repo = git.Repo('.')
bot.msg_sent = {}
sbg_base = ['598390820655071277', '604277350791774208', '599517945571573800', '674788690614026279',
            '602627694332477440', '640708611097493561', '600259912022360117', '732020286760681594',
            '593203392524976138', '593163327304237098', '658462156391448586', '686404956164456670',
            '593161930273849354', '743545013463679117', '594951070568939553', '596113518835531827',
            '596561055485001758', '596950202502479888', '596951779724492813', '646282949704024065',
            '646281623347789834', '592794714051182602', '594010023496122384', '611414047446794270',
            '597071614756126720', '620863493452726272', '630839251038109707', '718494182427197511',
            '695355671037870082', '695355722665558058', '695355725408632911', '695355727589539983',
            '695355730412306454', '747024592471588887', '747023898406682624', '747024582820495411',
            '747024586025074739', '776556977047339068', '782649526912942090', '782649542604619807',
            '782649534429003776', '782649530649804850', '782649538778628157', '782649547645911061',
            '717618429728784454', '693272417224622141', '695900911389638666', '751928992092651591',
            '783824492651872306', '778709363979845702', '787881953331249152', '787881958063341568',
            '787881962274684988', '787881966392442911', '787881970872746025']

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


@bot.event
async def on_command_error(ctx, error):
    traceback.print_exception(type(error), error, error.__traceback__)
    traceback_data = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    version = repo.head.object.hexsha[:8]
    params = {'exc_string': str(error), 'exc_content': traceback_data,
              'time': int(time.time()), 'msg_author_name': str(ctx.author), 'msg_author_id': str(ctx.author.id),
              'msg_guild_name': ctx.guild.name,
              'msg_guild_id': str(ctx.guild.id), 'msg_channel_name': ctx.channel.name,
              'msg_channel_id': str(ctx.channel.id),
              'msg_id': str(ctx.message.id), 'msg_cont': ctx.message.content,
              'bot': 'SkyBlockZ Giveaways', 'version': version,
              'key': tokens['error']}
    async with aiohttp.ClientSession(loop=bot.loop) as cs:
        resp = await cs.post('https://error.robothanzo.dev/add', params=params)
        track_url = f'https://error.robothanzo.dev/view/{(await resp.json())["track_uuid"]}'
    await ctx.send(f'Oh crap, something went VERY WRONG, the exception has been recorded at {track_url}')


@tasks.loop(hours=12)
async def clear_msg_sent():
    bot.msg_sent = {}


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


@tasks.loop(seconds=1)
async def invalidate_and_check_ongoing_gates():
    if not bot.loaded_db:
        return
    await db.clear_expired_gates(bot.db)
    for iiiii in await db.get_ending_soon_gates(bot.db):
        msg = await bot.get_channel(int(iiiii['channel_id'])).fetch_message(int(iiiii['id']))
        for i in msg.reactions:
            async for ii in i.users():
                if ii.bot:
                    continue
                if isinstance(ii, discord.User):
                    await i.remove(ii)
                    continue
                ii_roles = [iii.id for iii in ii.roles]
                if not any(iii in ii_roles for iii in iiiii['requirements']):
                    await i.remove(ii)
                    logging.info(f'Removed {str(ii.id)} from {str(iiiii["id"])}')


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
        # ask for channel, time, winners, prize name, showcase image, donor, requirements
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


async def send_message_if_needed(guild, gates, member):
    if gates['id'] not in bot.msg_sent:
        bot.msg_sent[gates['id']] = []
    if member.id not in bot.msg_sent[gates['id']]:
        bot.msg_sent[gates['id']].append(member.id)
        embed = discord.Embed(title='\u274c**|**Giveaway Participation Attempt Failed',
                              colour=discord.Colour.red())
        req_roles = [guild.get_role(iiii) for iiii in gates['requirements']]
        embed.add_field(name='You are missing **one of the following** roles: ',
                        value='\n'.join([iiii.name for iiii in req_roles]), inline=False)
        embed.add_field(name='You can check the following spreadsheet to learn how to get them: ',
                        value='https://docs.google.com/document/d/1r4rs_7KsopvFD99SQUKYteLjkXiJcI5jwlW5QNZFfgE',
                        inline=False)
        await member.send(embed=embed)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    giveaway = await db.search_giveaway(bot.db, 'message_id', payload.message_id)
    gates = await db.search_gate(bot.db, payload.channel_id, payload.message_id)
    if giveaway is None and gates is None:
        return
    if gates is not None:
        guild = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        roles = [iii.id for iii in member.roles]
        if not any(iii in roles for iii in gates['requirements']):
            message = await bot.get_channel(gates['channel_id']).fetch_message(gates['id'])
            for i in message.reactions:
                i: discord.Reaction
                if str(payload.emoji) == str(i.emoji):
                    await i.remove(bot.get_user(payload.user_id))
                    if member is None:
                        pass
                    else:
                        await send_message_if_needed(guild, gates, member)
                    logging.info(f'Removed {str(payload.user_id)} from {str(payload.message_id)}')
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
    if ga['requirements']:
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


@bot.command(name='quick',
             usage='quick <channel> <length> <winner_count> <host> <prize_name>',
             description='Creates a giveaway with one-line command, but without the ability to specify optional parameters, such as showcase image and requirements',
             aliases=['q'])
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def quick(ctx: commands.Context, channel: discord.TextChannel, length: typing.Union[int, str], winner_count: int,
                host: discord.Member, *, prize_name: str):
    await ctx.send(
        f'Giveaway will be created with the following parameters:\n\nCHN {channel.mention}\nLGT `{length}`\nWNC `{winner_count}`\nPZN `{prize_name}`',
        allowed_mentions=discord.AllowedMentions.none())
    next_id = await db.get_next_id(bot.db)
    creation_time = int(time.time())
    embed = discord.Embed(title=prize_name,
                          colour=discord.Colour.from_rgb(random.randint(0, 255), random.randint(0, 255),
                                                         random.randint(0, 255)))
    embed.add_field(name='Hosted By', value=host.mention)
    embed.add_field(name='Winners', value=str(winner_count))
    embed.timestamp = datetime.datetime.utcfromtimestamp(creation_time + length)
    embed.set_footer(text=f'ID: {next_id}| Ends At')
    sent = await channel.send(embed=embed)
    sent_ctx = await bot.get_context(sent)
    await db.create_giveaway(bot.db, next_id, sent_ctx, length, prize_name, host.id, winner_count, None,
                             [],
                             creation_time)
    await sent.add_reaction(tada_emoji)


@bot.group(name='gate', usage='gate <subcommand>', description='A series of reaction gates related commands',
           invoke_without_command=True)
async def gate(ctx):
    await ctx.send(
        'You shall be using some other commands, instead of this one, think about what you could have done in this 3 seconds typing and wating for this message to appear...')


async def parse_requirements(requirements: str):
    requirements = requirements.split(' ')
    for req in requirements:
        if not req.isdigit():
            res = await db.get_gate_template(bot.db, req)
            if res is not None:
                ind = requirements.index(req)
                requirements.remove(req)
                for i in range(len(res)):
                    requirements.insert(i + ind, res[i])
    requirements = [int(i) for i in requirements]
    return requirements


@gate.command(name='add', usage='gate add <channel> <message_id> <interval> <requirements>',
              description='Adds a requirement gate to the message, reacting any reactions on the message without matching the requirements will be denied and have it removed\nInterval formats as <amount><suffix> where available suffixes are w,d,h,m,s\nRequirements shall be splited with spaces')
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def add(ctx: commands.Context, channel: discord.TextChannel, message_id: int, interval: str, *,
              requirements: str):
    interval = int(convert_time(interval))
    requirements = await parse_requirements(requirements)
    try:
        await db.add_gate(bot.db, channel.id, message_id, interval, requirements)
    except asyncpg.UniqueViolationError:
        await ctx.send('There has been already a gate on this message')
        return
    msg = await channel.fetch_message(message_id)
    req_ping = [f'<@&{i}>' for i in requirements]
    await ctx.send(
        f'Gate added, with the following roles: {" ".join(req_ping)}, existing illegal reactions are being removed',
        allowed_mentions=discord.AllowedMentions.none())
    for i in msg.reactions:
        async for ii in i.users():
            if ii.bot:
                continue
            if isinstance(ii, discord.User):
                await i.remove(ii)
                continue
            ii_roles = [iii.id for iii in ii.roles]
            if not any(iii in ii_roles for iii in requirements):
                await i.remove(ii)
                logging.info(f'Removed {str(ii.id)} from {str(message_id)}')


@gate.command(name='modify', usage='gate modify <channel> <message_id> <new_requirements>',
              description='Changes the requirement gate of message to new_requirements')
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def modify(ctx: commands.Context, channel: discord.TextChannel, message_id: int, new_requirements: str):
    pr = await parse_requirements(new_requirements)
    await db.modify_gate(bot.db, channel.id, message_id, pr)
    req_ping = [f'<@&{i}>' for i in pr]
    await ctx.send(f'Gate modified, with the new requirements: {" ".join(req_ping)}',
                   allowed_mentions=discord.AllowedMentions.none())


@gate.command(name='remove', usage='gate remove <channel> <message_id>', aliases=['delete'])
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def remove(ctx: commands.Context, channel: discord.TextChannel, message_id: int):
    await db.remove_gate(bot.db, channel.id, message_id)
    await ctx.send('Gate removed.')


@gate.command(name='qualifycheck', usage='gate qualifycheck <channel> <message_id>')
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def qualifycheck(ctx: commands.Context, channel: discord.TextChannel, message_id: int):
    msg = await channel.fetch_message(message_id)
    bombarded = 0
    requirements = (await db.search_gate(bot.db, channel.id, message_id))['requirements']
    for i in msg.reactions:
        async for ii in i.users():
            if ii.bot:
                continue
            if isinstance(ii, discord.User):
                await i.remove(ii)
                bombarded += 1
                continue
            ii_roles = [iii.id for iii in ii.roles]
            if not any(iii in ii_roles for iii in requirements):
                await i.remove(ii)
                bombarded += 1
                logging.info(f'Removed {str(ii.id)} from {str(message_id)}')
    await ctx.send(f'{bombarded} users have lost their chance to the giveaway, feelin\' good')


@gate.command(name='bombard', usage='bombard',
              description='Checks ALL the gates for the current server and remove those who don\'t qualify')
@commands.has_any_role(593163327304237098, 764541727494504489, 637823625558229023, 598197239688724520)
async def bombard(ctx: commands.Context):
    gates = await db.list_gates(bot.db)
    messages = []
    for gate in gates:
        bombarded = 0
        msg = await bot.get_channel(gate['channel_id']).fetch_message(gate['id'])
        for i in msg.reactions:
            async for ii in i.users():
                if ii.bot:
                    continue
                if isinstance(ii, discord.User):
                    await i.remove(ii)
                    bombarded += 1
                    continue
                ii_roles = [iii.id for iii in ii.roles]
                if not any(iii in ii_roles for iii in gate['requirements']):
                    await i.remove(ii)
                    bombarded += 1
                    logging.info(f'Removed {str(ii.id)} from {str(msg.id)}')
        messages.append(f'Removed {bombarded} people from {msg.jump_url}')
    await ctx.send('\n'.join(messages))


@gate.group(name='template', usage='template <subcommand>', description='Manage the gate templates',
            invoke_without_command=True)
async def template(ctx):
    await ctx.send('Should you be using my sub-commands now?')


@template.command(name='add', usage='add <template_id> <roles>')
async def add_template(ctx: commands.Context, template_id: str, roles: str):
    roles = await parse_requirements(roles)
    await db.add_gate_template(bot.db, template_id, roles)
    res = await db.get_gate_template(bot.db, template_id)
    await ctx.send(
        f'Template {template_id} created with the following roles: {" ".join(["<@&" + str(i) + ">" for i in res])}')


@template.command(name='remove', usage='remove <template_id>')
async def remove(ctx: commands.Context, template_id: str):
    await db.remove_gate_template(bot.db, template_id)
    await ctx.send('Template removed.')


@template.command(name='alias', usage='alias <template_id> <aliases separated by space>')
async def alias(ctx: commands.Context, template_id: str, aliases: str):
    await db.add_template_alias(bot.db, template_id, aliases.split(' '))
    await ctx.send('Template aliased.')


@template.command(name='unalias', usage='unalias <template_id> <aliases separated by space>')
async def unalias(ctx: commands.Context, template_id: str, aliases: str):
    for alias in aliases.split(' '):
        await db.remove_template_alias(bot.db, template_id, alias)
    await ctx.send(f'Alias{"es" if len(aliases.split(" ")) > 1 else ""} removed.')


@template.command(name='addrole', usage='addrole <template_id> <roles>')
async def addrole(ctx: commands.Context, template_id: str, roles: str):
    await db.purge_template_invalid_roles(bot.db, ctx.guild, template_id)
    roles = await parse_requirements(roles)
    for role in roles:
        await db.add_template_role(bot.db, template_id, role)
    res = await db.get_gate_template(bot.db, template_id)
    await ctx.send(
        f'Template {template_id} added roles now with the following roles: {" ".join(["<@&" + str(i) + ">" for i in res])}')


@template.command(name='removerole', usage='removerole <template_id> <roles>', aliases=['unrole', 'rmrole'])
async def rmrole(ctx: commands.Context, template_id: str, roles: str):
    await db.purge_template_invalid_roles(bot.db, ctx.guild, template_id)
    roles = await parse_requirements(roles)
    for role in roles:
        await db.remove_template_role(bot.db, template_id, role)
    res = await db.get_gate_template(bot.db, template_id)
    await ctx.send(
        f'Template {template_id} removed roles now with the following roles: {" ".join(["<@&" + str(i) + ">" for i in res])}')


@bot.command(name='reboot')
@commands.is_owner()
async def reboot(ctx):
    await ctx.send('Shutting down...')
    await bot.logout()


check_giveaways.start()
invalidate_and_check_ongoing_gates.start()
bot.run(tokens['token'])
