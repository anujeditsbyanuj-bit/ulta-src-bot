import motor.motor_asyncio
import datetime
import random
import string
from config import DB_NAME, DB_URI
from logger import LOGGER
logger = LOGGER(__name__)
class Database:
   
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
    def new_user(self, id, name):
        return dict(
            id = id,
            name = name,
            session = None,
            daily_usage = 0, # Added: Track saves
            limit_reset_time = None # Added: Track 24h reset time
        )
   
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)
        logger.info(f"New user added to DB: {id} - {name}")
   
    async def is_user_exist(self, id):
        user = await self.col.find_one({'id':int(id)})
        return bool(user)
   
    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count
    async def get_all_users(self):
        return self.col.find({})
    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})
        logger.info(f"User deleted from DB: {user_id}")
    async def set_session(self, id, session):
        await self.col.update_one({'id': int(id)}, {'$set': {'session': session}})
    async def get_session(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('session')
    # Caption Support
    async def set_caption(self, id, caption):
        await self.col.update_one({'id': int(id)}, {'$set': {'caption': caption}})
    async def get_caption(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('caption', None)
    async def del_caption(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'caption': ""}})
    # Thumbnail Support
    async def set_thumbnail(self, id, thumbnail):
        await self.col.update_one({'id': int(id)}, {'$set': {'thumbnail': thumbnail}})
    async def get_thumbnail(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('thumbnail', None)
    async def del_thumbnail(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'thumbnail': ""}})
    # Auto-Rename Template Support
    async def set_autorename(self, id, template):
        if template:
            await self.col.update_one({'id': int(id)}, {'$set': {'autorename': template}}, upsert=True)
        else:
            await self.col.update_one({'id': int(id)}, {'$unset': {'autorename': ""}}, upsert=True)
    async def get_autorename(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('autorename') if user else None
    # Filename Prefix / Suffix Support
    async def set_prefix(self, id, prefix):
        if prefix:
            await self.col.update_one({'id': int(id)}, {'$set': {'prefix': prefix}}, upsert=True)
        else:
            await self.col.update_one({'id': int(id)}, {'$unset': {'prefix': ""}}, upsert=True)
    async def get_prefix(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('prefix') if user else None
    async def set_suffix(self, id, suffix):
        if suffix:
            await self.col.update_one({'id': int(id)}, {'$set': {'suffix': suffix}}, upsert=True)
        else:
            await self.col.update_one({'id': int(id)}, {'$unset': {'suffix': ""}}, upsert=True)
    async def get_suffix(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('suffix') if user else None
    # Metadata Title Support
    async def set_metadata(self, id, text):
        if text:
            await self.col.update_one({'id': int(id)}, {'$set': {'metadata_text': text}}, upsert=True)
        else:
            await self.col.update_one({'id': int(id)}, {'$unset': {'metadata_text': ""}}, upsert=True)
    async def get_metadata(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('metadata_text') if user else None
    # Watermark Support
    async def set_watermark(self, id, text):
        if text:
            await self.col.update_one({'id': int(id)}, {'$set': {'watermark_text': text}}, upsert=True)
        else:
            await self.col.update_one({'id': int(id)}, {'$unset': {'watermark_text': ""}}, upsert=True)
    async def get_watermark(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('watermark_text') if user else None
    async def set_watermark_position(self, id, position):
        await self.col.update_one({'id': int(id)}, {'$set': {'watermark_position': position}}, upsert=True)
    async def get_watermark_position(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('watermark_position') if user else 'bottom_right'
    # Rexbots / Modified by You
    # Don't Remove Credit
    # Telegram Channel @RexBots_Official
    # Premium Support
    async def add_premium(self, id, expiry_date):
        # When user buys premium, we also reset their limits just in case
        await self.col.update_one({'id': int(id)}, {
            '$set': {
                'is_premium': True,
                'premium_expiry': expiry_date,
                'daily_usage': 0,
                'limit_reset_time': None
            }
        })
        logger.info(f"User {id} granted premium until {expiry_date}")
    async def remove_premium(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_premium': False, 'premium_expiry': None}})
        logger.info(f"User {id} removed from premium")
    async def check_premium(self, id):
        user = await self.col.find_one({'id': int(id)})
        if user and user.get('is_premium'):
            return user.get('premium_expiry')
        return None
    async def get_premium_users(self):
        return self.col.find({'is_premium': True})
    # Ban Support
    async def ban_user(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_banned': True}})
        logger.warning(f"User banned: {id}")
    async def unban_user(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_banned': False}})
        logger.info(f"User unbanned: {id}")
    async def is_banned(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('is_banned', False)
    # Dump Chat Support
    async def set_dump_chat(self, id, chat_id):
        await self.col.update_one({'id': int(id)}, {'$set': {'dump_chat': int(chat_id)}})
    async def get_dump_chat(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('dump_chat', None)
    # Batch Limit Support (user-configurable, capped server-side by plan)
    async def set_batch_limit(self, id, limit_val):
        await self.col.update_one({'id': int(id)}, {'$set': {'batch_limit': int(limit_val)}})
    async def get_batch_limit(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('batch_limit') if user else None
    # Lifetime Saved-Files Counter (for /status)
    async def increment_total_saved(self, id):
        await self.col.update_one({'id': int(id)}, {'$inc': {'total_saved': 1}})
    async def get_total_saved(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('total_saved', 0) if user else 0
    # Optional Free-Access Token Gate (URL-shortener based, disabled unless configured)
    async def set_free_token(self, id, expires_at):
        await self.col.update_one({'id': int(id)}, {'$set': {'free_token_expiry': expires_at}})
    async def get_free_token_expiry(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('free_token_expiry') if user else None
    async def has_valid_free_token(self, id):
        expiry = await self.get_free_token_expiry(id)
        if not expiry:
            return False
        return datetime.datetime.now() < expiry
    # Bot Mode (Freemium / Paid) — stored on a fixed settings doc
    async def get_bot_mode(self):
        doc = await self.db.settings.find_one({'_id': 'bot_mode'})
        return doc.get('mode', 'paid') if doc else 'paid'
    async def set_bot_mode(self, mode):
        await self.db.settings.update_one({'_id': 'bot_mode'}, {'$set': {'mode': mode}}, upsert=True)
    # Custom Bot Token Support (/setbot, /rembot)
    async def set_custom_bot(self, id, bot_token):
        await self.col.update_one({'id': int(id)}, {'$set': {'custom_bot_token': bot_token}})
    async def get_custom_bot(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('custom_bot_token') if user else None
    async def remove_custom_bot(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'custom_bot_token': ""}})
    # Referral System
    async def ensure_referral_data(self, id):
        user = await self.col.find_one({'id': int(id)})
        if user and user.get('referral', {}).get('code'):
            return
        code = None
        for _ in range(5):
            candidate = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await self.col.find_one({'referral.code': candidate}):
                code = candidate
                break
        code = code or ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        await self.col.update_one(
            {'id': int(id)},
            {'$set': {
                'referral.code': code,
                'referral.ftm_bucks': 0,
                'referral.total_referrals': 0,
                'referral.referred_users': [],
                'referral.referred_by': None,
            }},
            upsert=True
        )
    async def get_referral_info(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('referral') if user else None
    async def get_user_by_referral_code(self, code):
        return await self.col.find_one({'referral.code': code})
    async def add_referral(self, referrer_id, new_user_id, new_user_name, reward_bucks):
        await self.col.update_one(
            {'id': int(referrer_id)},
            {
                '$inc': {'referral.ftm_bucks': reward_bucks, 'referral.total_referrals': 1},
                '$push': {'referral.referred_users': {
                    'id': int(new_user_id), 'name': new_user_name,
                    'referred_at': datetime.datetime.now().isoformat()
                }}
            }
        )
        await self.col.update_one({'id': int(new_user_id)}, {'$set': {'referral.referred_by': int(referrer_id)}})
    async def deduct_referral_bucks(self, id, amount):
        """Atomically checks-and-deducts in a single update_one call, using a
        $gte filter on the current balance as the guard. Without this, a
        separate "read balance, then deduct" sequence leaves a window where
        two concurrent redeems (e.g. a double-tap) can both pass the balance
        check before either deduction lands, letting a user redeem more bucks
        than they actually have (or go negative). Returns True if the
        balance was sufficient and the deduction was applied, False
        otherwise (e.g. balance changed/was insufficient in between)."""
        result = await self.col.update_one(
            {'id': int(id), 'referral.ftm_bucks': {'$gte': amount}},
            {'$inc': {'referral.ftm_bucks': -amount}}
        )
        return result.modified_count > 0
    async def get_referral_leaderboard(self, skip=0, limit=10):
        cursor = self.col.find({'referral.total_referrals': {'$gt': 0}}) \
            .sort('referral.total_referrals', -1).skip(skip).limit(limit)
        return [u async for u in cursor]
    async def count_referral_leaderboard(self):
        return await self.col.count_documents({'referral.total_referrals': {'$gt': 0}})
    # Delete/Replace Words Support
    # RSS Feed Support (per-user subscriptions for auto-download)
    async def add_rss_feed(self, id, name, url, initial_seen=None):
        user = await self.col.find_one({'id': int(id)})
        feeds = (user or {}).get('rss_feeds', []) or []
        feeds.append({'name': name, 'url': url, 'seen': initial_seen or []})
        await self.col.update_one({'id': int(id)}, {'$set': {'rss_feeds': feeds}}, upsert=True)

    async def get_rss_feeds(self, id):
        user = await self.col.find_one({'id': int(id)})
        return (user or {}).get('rss_feeds', []) or []

    async def remove_rss_feed(self, id, index):
        feeds = await self.get_rss_feeds(id)
        if 0 <= index < len(feeds):
            feeds.pop(index)
            await self.col.update_one({'id': int(id)}, {'$set': {'rss_feeds': feeds}})
            return True
        return False

    async def mark_rss_seen(self, id, feed_index, guid, cap=300):
        feeds = await self.get_rss_feeds(id)
        if 0 <= feed_index < len(feeds):
            seen = feeds[feed_index].get('seen') or []
            seen.append(guid)
            feeds[feed_index]['seen'] = seen[-cap:]
            await self.col.update_one({'id': int(id)}, {'$set': {'rss_feeds': feeds}})

    async def get_all_rss_users(self):
        return self.col.find({'rss_feeds': {'$exists': True, '$ne': []}})

    async def set_delete_words(self, id, words):
        await self.col.update_one({'id': int(id)}, {'$addToSet': {'delete_words': {'$each': words}}})
    async def get_delete_words(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('delete_words', [])
    async def remove_delete_words(self, id, words):
        await self.col.update_one({'id': int(id)}, {'$pull': {'delete_words': {'$in': words}}})
    async def set_replace_words(self, id, repl_dict):
        user = await self.col.find_one({'id': int(id)})
        current_repl = user.get('replace_words', {})
        current_repl.update(repl_dict)
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': current_repl}})
    async def get_replace_words(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('replace_words', {})
    async def remove_replace_words(self, id, words):
        user = await self.col.find_one({'id': int(id)})
        current_repl = user.get('replace_words', {})
        for w in words:
            current_repl.pop(w, None)
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': current_repl}})
    # --------------------------------------------------------
    # NEW FEATURES: Daily Limits (Free User Restriction)
    # --------------------------------------------------------
    async def check_limit(self, id):
        """
        Checks if a user has hit their daily limit.
        Returns: True if BLOCKED (limit reached), False if ALLOWED.
        """
        user = await self.col.find_one({'id': int(id)})
        if not user:
            return False # Should be added via add_user, but safe fallback
       
        # 1. Premium Check: Always allowed
        if user.get('is_premium'):
            return False
        # 2. Check Time Reset
        now = datetime.datetime.now()
        reset_time = user.get('limit_reset_time')
       
        # If reset time has passed or was never set, reset count to 0
        if reset_time is None or now >= reset_time:
            await self.col.update_one(
                {'id': int(id)},
                {'$set': {'daily_usage': 0, 'limit_reset_time': None}}
            )
            return False # Allowed (count is 0)
        # 3. Check Count
        usage = user.get('daily_usage', 0)
        if usage >= 10:
            return True # Blocked
       
        return False # Allowed
    async def add_traffic(self, id):
        """
        Increments usage count.
        If it's the first save of the cycle, sets the 24h timer.
        """
        user = await self.col.find_one({'id': int(id)})
       
        # If premium, do nothing or track stats if you want (currently strictly for limit logic)
        if user.get('is_premium'):
            return
        now = datetime.datetime.now()
        reset_time = user.get('limit_reset_time')
        # Logic: If timer is not running (None), start it for 24 hours from NOW.
        if reset_time is None:
            new_reset_time = now + datetime.timedelta(hours=24)
            await self.col.update_one(
                {'id': int(id)},
                {'$set': {'daily_usage': 1, 'limit_reset_time': new_reset_time}}
            )
        else:
            # Just increment
            await self.col.update_one(
                {'id': int(id)},
                {'$inc': {'daily_usage': 1}}
            )
db = Database(DB_URI, DB_NAME)
