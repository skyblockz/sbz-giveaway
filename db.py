import random
import time

import asyncpg
import discord
from discord.ext import commands


class NotEnoughParticipants(Exception):
    def __init__(self):
        super().__init__('Insufficient amount of participants have participated in this giveaway')


class NoParticipants(Exception):
    def __init__(self):
        super().__init__('No participants have participated in this giveaway')


async def ensure_database_validity(db: asyncpg.pool.Pool):
    """
    Ensures the database table is valid

    :param db: The database object
    :return: None
    """
    query = """
    CREATE TABLE IF NOT EXISTS giveaways
    (
        id           int unique    not null primary key,
        message_id   bigint        not null,
        channel_id   bigint        not null,
        created_at   bigint        not null,
        length       bigint        not null,
        winner_count int           not null,
        prize_name   text          not null,
        image        text,
        host         text          not null,
        requirements bigint[],
        participants bigint[],
        winners      bigint[]
    );
    """
    await db.execute(query)


async def get_next_id(db: asyncpg.pool.Pool):
    """
    Get the next giveaway ID

    :param db: The database object
    :return: The next giveaway ID to be used as an int
    """
    query = """
    SELECT id FROM giveaways ORDER BY id DESC LIMIT 1
    """
    res = await db.fetch(query)
    if res == []:
        return 0
    res = res[0]['id']
    return res + 1


async def create_giveaway(db: asyncpg.pool.Pool, id: int, ctx: commands.Context, length: int, prize_name: str,
                          host: str,
                          winner_count: int = 1,
                          image: str = None,
                          requirements=None):
    """
    Create a new giveaway

    :param db: The database object
    :param id: The id of the giveaway, can be fetched with `get_next_id`
    :param ctx: Context of the giveaway message, used to obatin `message_id` and `channel_id`
    :param length: How long should the giveaway last for (in seconds)
    :param prize_name: The name of the prize
    :param host: The host of the giveaway
    :param winner_count: How many winner should there be
    :param image: The image of the giveaway (Optional)
    :param requirements: A list with all the roles that is allowed to participate in the giveaway (Optional)
    :return: None
    """
    if requirements is None:
        requirements = []
    query = """
    INSERT INTO giveaways 
    (id, message_id, channel_id, created_at, length, winner_count, prize_name, image, host,requirements) VALUES 
    ($1, $2 ,$3, $4, $5, $6, $7, $8, $9, $10)
    """
    await db.execute(query, id, ctx.message.id, ctx.channel.id, int(time.time()), length, winner_count, prize_name,
                     image, host, requirements)


async def add_participant(db: asyncpg.pool.Pool, id: int, member: discord.Member):
    """
    Adds a new participant to the giveaway
    Note: This also checks the requirements

    :param db: The database object
    :param id: The giveaway ID
    :param member: The member object of the participant to add
    :return: bool : If the the user has qualified for the giveaway or not
    """
    query = """
    SELECT requirements FROM giveaways WHERE id=$1
    """
    reqs = (await db.fetch(query, id))[0]['requirements']
    user_role_ids = [role.id for role in member.roles]
    qualified = False
    for req in reqs:
        if req in user_role_ids:
            qualified = True
            break
    if len(reqs) == 0:
        qualified = True
    if not qualified:
        return False
    query = """
    UPDATE giveaways SET participants = array_append(participants, $1)
    """
    await db.execute(query, member.id)
    return True


async def roll_winner(db: asyncpg.pool.Pool, id: int):
    """
    Rolls winner(s) from the database
    Winner count automatically fetched
    
    :param db: The database object
    :param id: The giveaway ID
    :raises NotEnoughParticipants
    :raises NoParticipant
    :return: The winner's ID
    """
    query = """
    SELECT participants, winner_count FROM giveaways WHERE id=$1
    """
    res = await db.fetch(query, id)
    participants = res[0]['participants']
    winner_count = res[0]['winner_count']
    if len(participants) == 0:
        query = """
            UPDATE giveaways SET winners=$1 WHERE id=$2
            """
        await db.execute(query, [0], id)
        raise NoParticipants
    if len(participants) <= winner_count:
        query = """
                    UPDATE giveaways SET winners=$1 WHERE id=$2
                    """
        await db.execute(query, [0], id)
        raise NotEnoughParticipants
    else:
        winners = random.sample(participants, winner_count)
    query = """
    UPDATE giveaways SET winners=$1 WHERE id=$2
    """
    await db.execute(query, winners, id)
    return winners


async def get_need_rolling_giveaways(db: asyncpg.pool.Pool):
    """
    Fetches all giveaways that has ended and does not have a winner
    Note: this does not do any actions with it, manually rolling is necessary

    :param db: The database object
    :return: The giveaway's ID(s) in a list
    """
    query = """
    SELECT id, created_at, length FROM giveaways WHERE winners IS NULL
    """
    res = await db.fetch(query)
    ret = []
    for i in res:
        if i['created_at'] + i['length'] < int(time.time()):
            ret.append(i['id'])
        else:
            continue
    return ret


async def get_info_of_giveaway(db: asyncpg.pool.Pool, id: int):
    """
    Fetches all informations stored in the database of the giveaway

    :param db: The database object
    :param id: The giveaway ID
    :return: A dict that contains all informations stored in the database about the giveaway
    """
    query = """
    SELECT * FROM giveaways WHERE id=$1
    """
    res = await db.fetch(query, id)
    return dict(res[0])
