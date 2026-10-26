import http.cookiejar
import time
import httpx

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1

# Basic API
s = httpx.CookieStore()
s.set("name", "value", domain="example.com", path="/")
check("basic get", s["name"] == "value")
check("basic get domain", s.get("name", domain="example.com") == "value")
s["foo"] = "bar"
check("setitem", s["foo"] == "bar")
check("len", len(s) == 2)
check("iter", set(s) == {"name", "foo"})
del s["foo"]
check("del", "foo" not in s)
s.set("a", "1"); s.set("b", "2")
s.delete("a")
check("delete", "a" not in s)
s.clear()
check("clear", len(s) == 0)
print("basic", ok); ok=0

# Validation
try:
    httpx.CookieStore(max_cookies="x")
    raise AssertionError("no TypeError")
except TypeError:
    pass
try:
    httpx.CookieStore(max_cookies_per_domain="x")
    raise AssertionError("no TypeError")
except TypeError:
    pass
try:
    httpx.CookieStore(max_cookies=-1)
    raise AssertionError("no ValueError")
except ValueError:
    pass
try:
    httpx.CookieStore(max_cookies_per_domain=-1)
    raise AssertionError("no ValueError")
except ValueError:
    pass
httpx.CookieStore(max_cookies=None, max_cookies_per_domain=None)
httpx.CookieStore(max_cookies=0, max_cookies_per_domain=0)
print("validation ok")

# Eviction
s = httpx.CookieStore(max_cookies=3)
for i in range(4):
    s.set(f"c{i}", str(i))
check("global evict oldest", len(s) == 3 and "c0" not in s and "c3" in s)

s = httpx.CookieStore(max_cookies_per_domain=2)
s.set("a", "1", domain="example.com")
time.sleep(0.01)
s.set("b", "2", domain="example.com")
time.sleep(0.01)
s.set("c", "3", domain="example.com")
check("per-domain evict", len(s) == 2 and "a" not in s)

# per-domain first, then global
s = httpx.CookieStore(max_cookies=3, max_cookies_per_domain=1)
s.set("a", "1", domain="example.com")
s.set("b", "2", domain="example.com")  # per-domain evicts a
check("both evict1", "a" not in s and "b" in s)
s.set("c", "3", domain="example.org")
s.set("d", "4", domain="example.org")  # per-domain evicts c, global evicts b
check("both evict2", len(s) == 2 and "c" not in s and "d" in s)
print("eviction", ok); ok=0

# Extraction basic
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com/path"), headers={"set-cookie": "sessionid=123; Path=/; Domain=example.com"})
s.extract_cookies(r)
check("extract basic", s["sessionid"] == "123")
check("extract domain", s.get("sessionid", domain="example.com") == "123")

# Multiple cookies combined
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "a=1, b=2"})
s.extract_cookies(r)
check("combined cookies", s["a"] == "1" and s["b"] == "2")

# Expires comma
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "foo=bar; Expires=Wed, 21 Oct 2099 07:28:00 GMT"})
s.extract_cookies(r)
check("expires comma", s["foo"] == "bar")

# Combined with expires comma
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT, b=2"})
s.extract_cookies(r)
check("combined + expires comma", s["a"] == "1" and s["b"] == "2")

# Empty/malformed
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "malformed; =bad; good=ok; empty="})
s.extract_cookies(r)
check("malformed ignored", "malformed" not in s and "bad" not in s)
check("empty value valid", s["empty"] == "")

# Attributes without value ignore entire cookie
for attr in ("Domain", "Max-Age", "Expires"):
    s = httpx.CookieStore()
    r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": f"foo=bar; {attr}"})
    s.extract_cookies(r)
    check(f"missing {attr} ignored", len(s) == 0)
print("extraction", ok); ok=0

# Host-only vs domain
s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://example.com/path"), headers={"set-cookie": "host=1"}))
req = httpx.Request("GET", "http://example.com/path")
s.set_cookie_header(req)
check("host-only sent to exact", req.headers.get("cookie") == "host=1")
req = httpx.Request("GET", "http://www.example.com/path")
s.set_cookie_header(req)
check("host-only not sent to sub", req.headers.get("cookie") is None)

s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://www.example.com/path"), headers={"set-cookie": "dom=1; Domain=example.com"}))
req = httpx.Request("GET", "http://sub.example.com/path")
s.set_cookie_header(req)
check("domain sent to sub", req.headers.get("cookie") == "dom=1")
req = httpx.Request("GET", "http://example.com/path")
s.set_cookie_header(req)
check("domain sent to apex", req.headers.get("cookie") == "dom=1")
req = httpx.Request("GET", "http://badexample.com/path")
s.set_cookie_header(req)
check("domain not to unrelated", req.headers.get("cookie") is None)

# case-insensitive
s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://EXAMPLE.com/path"), headers={"set-cookie": "x=1; Domain=Example.COM"}))
req = httpx.Request("GET", "http://example.com/path")
s.set_cookie_header(req)
check("case insensitive", req.headers.get("cookie") == "x=1")

# Path matching
s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://example.com/sub/path"), headers={"set-cookie": "p=1; Path=/sub"}))
for url in ("http://example.com/sub", "http://example.com/sub/x"):
    req = httpx.Request("GET", url)
    s.set_cookie_header(req)
    check(f"path match {url}", req.headers.get("cookie") == "p=1")
req = httpx.Request("GET", "http://example.com/submarine")
s.set_cookie_header(req)
check("no path submarine", req.headers.get("cookie") is None)

# Default path
s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://example.com/sub/x"), headers={"set-cookie": "dp=1"}))
check("default path", s.get("dp", domain="example.com", path="/sub") == "1")
req = httpx.Request("GET", "http://example.com/sub/x")
s.set_cookie_header(req)
check("default path sent", req.headers.get("cookie") == "dp=1")
req = httpx.Request("GET", "http://example.com/other")
s.set_cookie_header(req)
check("default path not sent", req.headers.get("cookie") is None)

# Path not starting with / uses default
s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://example.com/sub/x"), headers={"set-cookie": "badpath=1; Path=sub"}))
check("bad path defaults", s.get("badpath", domain="example.com", path="/sub") == "1")
print("matching", ok); ok=0

# Secure
s = httpx.CookieStore()
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "sec=1; Secure"}))
check("secure stored", s["sec"] == "1")
req = httpx.Request("GET", "http://example.com/")
s.set_cookie_header(req)
check("secure not over http", req.headers.get("cookie") is None)
req = httpx.Request("GET", "https://example.com/")
s.set_cookie_header(req)
check("secure over https", req.headers.get("cookie") == "sec=1")
print("secure ok")

# Prefix rules
def extract_from(url, header):
    s = httpx.CookieStore()
    s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", url), headers={"set-cookie": header}))
    return s

s = extract_from("https://example.com/", "__Secure-foo=1; Secure")
check("__Secure- ok https", s["__Secure-foo"] == "1")
s = extract_from("http://example.com/", "__Secure-foo=1; Secure")
check("__Secure- no https", len(s) == 0)
s = extract_from("https://example.com/", "__Secure-foo=1")
check("__Secure- no secure", len(s) == 0)
s = extract_from("https://example.com/", "__Host-foo=1; Secure; Path=/")
check("__Host- ok", s["__Host-foo"] == "1")
s = extract_from("https://example.com/", "__Host-foo=1; Secure; Domain=example.com; Path=/")
check("__Host- with domain", len(s) == 0)
s = extract_from("https://example.com/", "__Host-foo=1; Secure; Path=/sub")
check("__Host- wrong path", len(s) == 0)
print("prefix ok")

# Expiry
s = httpx.CookieStore()
s.set("x", "1", domain="example.com")
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "x=2; Max-Age=0"})
s.extract_cookies(r)
check("max-age 0 deletes", len(s) == 0)

s = httpx.CookieStore()
s.set("x", "1", domain="example.com")
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "x=2; Expires=Wed, 21 Oct 2000 07:28:00 GMT"})
s.extract_cookies(r)
check("past expires deletes", len(s) == 0)

# Max-Age takes precedence over Expires
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "x=1; Expires=Wed, 21 Oct 2000 07:28:00 GMT; Max-Age=3600"})
s.extract_cookies(r)
check("max-age precedence future", s["x"] == "1")
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "x=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT; Max-Age=0"})
s.extract_cookies(r)
check("max-age precedence delete", len(s) == 0)

# Invalid expires doesn't prevent storing
s = httpx.CookieStore()
r = httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "x=1; Expires=not-a-date"})
s.extract_cookies(r)
check("invalid expires stored", s["x"] == "1")
print("expiry ok")

# Replacement resets creation order
s = httpx.CookieStore(max_cookies=2)
s.set("a", "1", domain="example.com")
s.set("b", "2", domain="example.com")
# replace a -> a becomes newest
s.extract_cookies(httpx.Response(200, request=httpx.Request("GET", "http://example.com"), headers={"set-cookie": "a=3; Domain=example.com"}))
check("replace resets order", s["a"] == "3")
# now set c; oldest is b
s.set("c", "3", domain="example.com")
check("replacement newest", "b" not in s and "a" in s and "c" in s)
print("replacement ok")

# Send ordering: longer path first, then older creation
s = httpx.CookieStore()
s.set("name", "short", domain="example.com", path="/")
s.set("name", "long", domain="example.com", path="/sub")
req = httpx.Request("GET", "http://example.com/sub/x")
s.set_cookie_header(req)
check("longer path first", req.headers.get("cookie") == "name=long")
print("ordering ok")

# CookieConflict
s = httpx.CookieStore()
s.set("name", "1", domain="example.com")
s.set("name", "2", domain="example.org")
try:
    s["name"]
    raise AssertionError("no conflict")
except httpx.CookieConflict:
    pass
check("conflict resolved by domain", s.get("name", domain="example.com") == "1")
print("conflict ok")

# update forms
s = httpx.CookieStore()
s2 = httpx.CookieStore()
s2.set("a", "1", domain="example.com")
s.update(s2)
check("update CookieStore", s.get("a", domain="example.com") == "1")

c = httpx.Cookies()
c.set("b", "2", domain="example.com")
s.update(c)
check("update Cookies", s.get("b", domain="example.com") == "2")

jar = http.cookiejar.CookieJar()
jar.set_cookie(http.cookiejar.Cookie(0, "c", "3", None, False, "example.com", True, False, "/", True, False, None, False, None, None, {}, False))
s.update(jar)
check("update CookieJar", s.get("c", domain="example.com") == "3")

s.update({"d": "4"})
check("update dict", s["d"] == "4")
s.update([("e", "5")])
check("update list", s["e"] == "5")
print("update ok")

# Global cookies (set with domain="") sent to any host
s = httpx.CookieStore()
s.set("g", "1")
req = httpx.Request("GET", "http://example.com/")
s.set_cookie_header(req)
check("global to any host", req.headers.get("cookie") == "g=1")
req = httpx.Request("GET", "http://other.org/")
s.set_cookie_header(req)
check("global to other host", req.headers.get("cookie") == "g=1")
print("global ok")

# Client integration
def handler(request):
    return httpx.Response(200, json={"cookie": request.headers.get("cookie")})
store = httpx.CookieStore()
store.set("session", "abc", domain="example.org")
client = httpx.Client(transport=httpx.MockTransport(handler))
client.cookies = store
resp = client.get("http://example.org/")
check("client uses CookieStore", resp.json()["cookie"] == "session=abc")
check("client.cookies is store", client.cookies is store)

# Request integration
store2 = httpx.CookieStore()
store2.set("k", "v", domain="example.com")
req = httpx.Request("GET", "http://example.com/", cookies=store2)
check("Request CookieStore", req.headers.get("cookie") == "k=v")
print("integration ok")

print("ALL PASSED")
