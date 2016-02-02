# Memcache API

from google.appengine.api import memcache

# Some_string is the value you'd like the memcache to be
memcache.set(some_key, some_string)
memcache.get(some_key)
memcache.delete(some_key)

# Can be any string
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT ANNOUNCEMENTS"