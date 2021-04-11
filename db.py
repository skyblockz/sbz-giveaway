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


class NotParticipated(Exception):
    def __init__(self):
        super().__init__('The requested removal object did not participated in this giveaway')


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
        host         bigint        not null,
        requirements bigint[],
        participants bigint[],
        winners      bigint[]
    );
    """
    await db.execute(query)
    gates_query = """
    CREATE TABLE IF NOT EXISTS giveaway_gates
    (
        id           bigint unique not null primary key,
        channel_id   bigint not null,
        ends_at      bigint,
        requirements bigint[]
    );
    """
    await db.execute(gates_query)
    gates_template_query = """
    CREATE TABLE IF NOT EXISTS giveaway_gates_template
    (
        id    text     not null unique primary key,
        alias text[],
        roles bigint[] not null
    );
    """
    await db.execute(gates_template_query)


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
    if not res:
        return 0
    res = res[0]['id']
    return res + 1


async def create_giveaway(db: asyncpg.pool.Pool, id: int, ctx: commands.Context, length: int, prize_name: str,
                          host: str,
                          winner_count: int = 1,
                          image: str = None,
                          requirements=None, starts_at: int = None):
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
    :param starts_at: Customize the starting time, if not provided uses int(time.time())
    :return: None
    """
    if requirements is None:
        requirements = []
    query = """
    INSERT INTO giveaways 
    (id, message_id, channel_id, created_at, length, winner_count, prize_name, image, host,requirements) VALUES 
    ($1, $2 ,$3, $4, $5, $6, $7, $8, $9, $10)
    """
    await db.execute(query, id, ctx.message.id, ctx.channel.id, int(time.time()) if starts_at is None else starts_at,
                     length, winner_count, prize_name,
                     image, host, requirements)


async def add_participant(db: asyncpg.pool.Pool, id: int, member: discord.Member):
    """
    Adds a new participant to the giveaway
    Note: This also checks the requirements

    :param db: The database object
    :param id: The giveaway ID
    :param member: A :class:`discord.Member` object of the participant to add
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
    UPDATE giveaways SET participants = array_append(participants, $1) WHERE id=$2
    """
    await db.execute(query, member.id, id)
    return True


async def remove_participant(db: asyncpg.pool.Pool, id: int, member: discord.Member):
    """
    Removes a participant from the giveaway participants

    :param db: The database object
    :param id: The giveaway ID
    :param member: A :class:`discord.Member` object for the participant to remove
    :raises NotParticipated
    :return: Nothing
    """
    query = """
        SELECT participants FROM giveaways WHERE id=$1
        """
    parts = (await db.fetch(query, id))[0]['participants']
    if member.id not in parts:
        raise NotParticipated
    query = """
        UPDATE giveaways SET participants = array_remove(participants, $1)
    """
    await db.execute(query, member.id)


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
    if participants is None:
        query = """
            UPDATE giveaways SET winners=$1 WHERE id=$2
            """
        await db.execute(query, [0], id)
        raise NoParticipants
    if len(participants) < winner_count:
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


async def search_giveaway(db: asyncpg.pool.Pool, target: str, value):
    """
    Search a giveaway based on the provided information

    :param db: The database object
    :param target: The column name (eg. message_id)
    :param value: The value of the target to search with
    :return: The first result as a dict or None if not found
    """
    query = f"""
    SELECT * FROM giveaways WHERE {target}=$1
    """
    res = await db.fetch(query, value)
    if len(res) == 0:
        return None
    return dict(res[0])


async def add_gate(db: asyncpg.pool.Pool, channel_id: int, message_id: int, last_for: int, requirements: list):
    """
    Adds a new gate to message_id

    :param db: The database object
    :param channel_id: The channel ID of the message to add gate to
    :param message_id: The message ID to add gate to
    :param last_for: How long should the system count the gate as valid before discarding
    :param requirements: What requirements shall be applied to
    :return: None
    """
    query = """
    INSERT INTO giveaway_gates
    (id, channel_id, ends_at, requirements) VALUES 
    ($1, $2 ,$3, $4)
    """
    await db.execute(query, message_id, channel_id, last_for + int(time.time()) + 5, requirements)


async def search_gate(db: asyncpg.pool.Pool, channel_id: int, message_id: int):
    """
    Searches for a gate in message_id

    :param db: The database object
    :param channel_id: The channel ID of message to search gates of
    :param message_id: The message ID to look for gates
    :return: The gate's information, None if not found
    """
    query = f"""
        SELECT * FROM giveaway_gates WHERE id=$1 AND channel_id=$2
        """
    res = await db.fetch(query, message_id, channel_id)
    if len(res) == 0:
        return None
    return dict(res[0])


async def list_gates(db: asyncpg.pool.Pool):
    """
    Lists all the gates in the database
    :param db: The database object
    :return: A list of all the gates in the database
    """
    query = """
    SELECT * FROM giveaway_gates
    """
    return await db.fetch(query)


async def remove_gate(db: asyncpg.pool.Pool, channel_id: int, message_id: int):
    """
    Removes a gate from message_id

    :param db: The database object
    :param channel_id: The channel ID of the message to be removed gate of
    :param message_id: The message ID to have the gate removed
    :return: None
    """
    query = """
    DELETE FROM giveaway_gates WHERE channel_id=$1 AND id=$2 
    """
    await db.execute(query, channel_id, message_id)


async def clear_expired_gates(db: asyncpg.pool.Pool):
    """
    Removes all gate that has expired
    :param db: The database object
    :return: None
    """
    query = """
    DELETE FROM giveaway_gates WHERE ends_at<=$1
    """
    await db.execute(query, int(time.time()))


async def get_ending_soon_gates(db: asyncpg.pool.Pool, remaining: int = 30):
    """
    Gets ending soon gates
    :param db: The database object
    :param remaining: The time to define "ending soon", defaults to 30
    :return: A list of ending soon gates
    """
    query = """
    SELECT * FROM giveaway_gates WHERE ends_at<=$1
    """
    res = await db.fetch(query, remaining + time.time())
    ret = []
    for i in res:
        ret.append(dict(i))
    return ret


async def modify_gate(db: asyncpg.pool.Pool, channel_id: int, message_id: int, new_requirements):
    """
    Modifies existing gate to have their `requirements` become `new_requirements`
    :param db: The database object.
    :param channel_id: The channel ID of the message gate to edit
    :param message_id: The message ID of the message gate to edit
    :param new_requirements: The new requirements to apply to the message gate
    :return: None
    """
    query = """
    UPDATE giveaway_gates
    SET
        requirements=$1
    WHERE
        channel_id=$2 AND id=$3   
    """
    await db.execute(query, new_requirements, channel_id, message_id)


async def get_gate_template(db: asyncpg.pool.Pool, template_id: str):
    """
    Fetches gate template using `template_id`, aliases are accepted
    :param db: The database object.
    :param template_id: The template id to query of, can be the alias of it
    :return: The template result, None if not found
    """
    query = """
    SELECT roles FROM giveaway_gates_template WHERE id=$1
    """
    res = await db.fetch(query, template_id)
    if len(res) == 0:
        aliased_query = """
        SELECT roles FROM giveaway_gates_template WHERE $1=ANY(alias)
        """
        res = await db.fetch(aliased_query, template_id)
        if len(res) == 0:
            return None
        else:
            return res[0]['roles']
    else:
        return res[0]['roles']


async def add_gate_template(db: asyncpg.pool.Pool, template_id: str, roles: list):
    """
    Adds another template to the gate templates
    :param db: The database object.
    :param template_id: The new template ID to be added to the database
    :param roles: The roles for the new template as a list of INTEGER
    :return: None
    """
    query = """
    INSERT INTO giveaway_gates_template (id, alias, roles) VALUES ($1, NULL, $2)
    """
    if not all([isinstance(x, int) for x in roles]):
        raise TypeError(f'Not of the values in roles are integer')
    await db.execute(query, template_id, roles)


async def remove_gate_template(db: asyncpg.pool.Pool, template_id: str):
    """
    Deletes a template from the database
    :param db: The database object
    :param template_id: The ID of the template to remove
    :return: None
    """
    query = """
    DELETE FROM giveaway_gates_template WHERE id=$1
    """
    await db.execute(query, template_id)


async def add_template_alias(db: asyncpg.pool.Pool, template_id: str, aliases: list):
    """
    Appends `aliases` into the current template aliases of `template_id`
    :param db: The database object
    :param template_id: The ID of the template to append alias of
    :param aliases: The aliases to append, as a list of STRING
    :return: All the aliases after appending
    """
    query = """
    UPDATE giveaway_gates_template SET alias=alias||$1 WHERE id=$2
    """
    if not all([isinstance(x, str) for x in aliases]):
        raise TypeError(f'Not of the values in roles are string')
    await db.execute(query, aliases, template_id)
    ret_query = """
    SELECT alias FROM giveaway_gates_template WHERE id=$1
    """
    res = await db.fetch(ret_query, template_id)
    return res[0]['alias']


async def remove_template_alias(db: asyncpg.pool.Pool, template_id: str, alias: str):
    """
    Removes an alias from a template
    :param db: The database object.
    :param template_id: The ID of the template to remove alias of
    :param alias: The alias to remove
    :return: All the aliases after removing
    """
    query = """
    UPDATE giveaway_gates_template SET alias=ARRAY_REMOVE(alias, $1) WHERE id=$2
    """
    await db.execute(query, alias, template_id)


async def add_template_role(db: asyncpg.pool.Pool, template_id: str, role_id: int):
    """
    Adds a role to a template
    :param db: The database object
    :param template_id: The ID of the template to add role to
    :param role_id: The ID of the role to be added
    :return: None
    """
    query = """
    UPDATE giveaway_gates_template SET roles=ARRAY_APPEND(roles, $1) WHERE id=$2
    """
    await db.execute(query, role_id, template_id)


async def remove_template_role(db: asyncpg.pool.Pool, template_id: str, role_id: int):
    """
    Removes a role from a template
    :param db: The database object
    :param template_id: The ID of the template to remove role of
    :param role_id: The ID of the role to be removed
    :return: None
    """
    query = """
    UPDATE giveaway_gates_template SET roles=ARRAY_REMOVE(roles, $2) WHERE id=$1
    """
    await db.execute(query, template_id, role_id)


async def purge_template_invalid_roles(db: asyncpg.pool.Pool, guild: discord.Guild, template_id: str):
    """
    Removes all invalid roles from a template
    :param db: The database object.
    :param guild: The guild object of the guild the roles are on
    :param template_id: The ID of the template to remove invalid roles of
    :return: The remaining roles
    """
    query = """
    SELECT roles FROM giveaway_gates_template WHERE id=$1
    """
    res = (await db.fetch(query, template_id))[0]['roles']
    kill_list = []
    for i in res:
        if not guild.get_role(i):
            kill_list.append(i)
    for j in kill_list:
        res.remove(j)
    update_query = """
    UPDATE giveaway_gates_template SET roles=$1 WHERE id=$2
    """
    await db.execute(update_query, res, template_id)
    return res


async def list_templates(db: asyncpg.pool.Pool):
    """
    Returns a list of templates in the database
    :param db: The database object
    :return: A list of templates
    """
    query = """
    SELECT * FROM giveaway_gates_template
    """
    return list(await db.fetch(query))
