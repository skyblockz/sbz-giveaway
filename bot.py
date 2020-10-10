import json
import logging

import asyncpg
import discord
from discord.ext import commands

import db


class SBZGiveawayBot(commands.Bot):
    def __init__(self, **options):
        super().__init__(options)
        self.db = None
        self.loaded_db = False


intents = discord.Intents.all()
intents.presences = False
logging.basicConfig(level=logging.INFO)
bot = SBZGiveawayBot(command_prefix='g$', intents=intents)
bot.load_extension('jishaku')

with open('token.json', 'r') as f:
    tokens = json.loads(f.read())


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


bot.run(tokens['token'])
