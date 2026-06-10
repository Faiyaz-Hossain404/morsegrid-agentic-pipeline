"""
Morsegrid Outfitters — synthetic data seeder.

Seeds an ecommerce store with TWO kinds of revenue-recovery opportunities:
  1. Abandoned carts            -> collection `abandoned_carts`  (time-sensitive)
  2. Dormant / lapsed customers -> scored from `customers` + `behavior_events`

The same agent pipeline (Planner -> Nurturer -> Sender) handles both.
All runtime DB access by the agents goes through the MongoDB MCP server; this
offline seeder uses pymongo (dev-time ETL, allowed by the hackathon rules).
"""
import os
import sys
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Ensure the root folder is in the python path so we can import from db
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.mongo import get_db_client

load_dotenv()
random.seed(22)  # reproducible data across runs
NOW = datetime.now(timezone.utc)


def days_ago(n):
    return NOW - timedelta(days=n)


def hours_ago(n):
    return NOW - timedelta(hours=n)


def rand_between(d_old, d_new):
    if d_new <= d_old:
        return d_old
    secs = (d_new - d_old).total_seconds()
    return d_old + timedelta(seconds=random.uniform(0, secs))


# ----------------------------------------------------------------------------
# 1. Product catalog (~50 distinct items — varied so vector search is meaningful)
# ----------------------------------------------------------------------------
def mk(pid, title, category, price, desc, tags,
       in_stock=True, created_days_ago=180, restocked_days_ago=None,
       cost=None, cost_ratio=0.45):
    cost = round(price * cost_ratio, 2) if cost is None else float(cost)
    doc = {
        "product_id": pid, "title": title, "category": category,
        "description": desc, "price": float(price), "cost": cost,
        "margin": round(price - cost, 2), "in_stock": in_stock,
        "tags": tags, "created_at": days_ago(created_days_ago),
    }
    if restocked_days_ago is not None:
        doc["restocked_at"] = days_ago(restocked_days_ago)
    return doc


PRODUCTS = [
    # --- Products that anchor the demo scenarios ---
    mk("P001", "Rallye Adventure Helmet", "Helmets", 350.00,
       "Dual-sport adventure helmet with drop-down sun visor and an ultra-wide field of view. Premium aerodynamics for long dual-sport and off-road touring.",
       ["adventure", "dual-sport", "touring", "off-road", "sun-visor"],
       cost=150.00, created_days_ago=300, restocked_days_ago=2),
    mk("P002", "Apex Carbon Full-Face Helmet", "Helmets", 599.00,
       "Ultra-lightweight aerospace carbon-fiber shell with maximum track ventilation and an optically correct race shield.",
       ["carbon", "full-face", "track", "race", "lightweight"], cost=250.00, created_days_ago=200),
    mk("P003", "Classic Leather Cafe Racer Jacket", "Jackets", 450.00,
       "Premium top-grain cowhide cafe racer jacket with CE armor inserts and a vintage distressed finish.",
       ["cafe-racer", "leather", "vintage", "ce-armor", "retro"],
       cost=180.00, created_days_ago=7),  # new arrival

    # --- Helmets ---
    mk("P004", "Vega Modular Flip-Up Helmet", "Helmets", 280.00,
       "Modular flip-up helmet with integrated drop-down sun visor and Bluetooth-ready speaker pockets.",
       ["modular", "flip-up", "commuter", "bluetooth-ready"]),
    mk("P005", "Street Jet Open-Face Helmet", "Helmets", 160.00,
       "Lightweight open-face jet helmet with a quick-release bubble visor for relaxed urban riding.",
       ["open-face", "jet", "urban", "retro"]),
    mk("P006", "Motocross MX Off-Road Helmet", "Helmets", 240.00,
       "Aggressive motocross helmet with extended peak and roost guard for off-road and enduro racing.",
       ["motocross", "mx", "off-road", "enduro"]),
    mk("P007", "Carbon GP Race Helmet", "Helmets", 720.00,
       "Track-homologated carbon GP helmet with aero spoiler and emergency quick-release cheek pads.",
       ["carbon", "gp", "race", "track", "aero"], in_stock=False),

    # --- Jackets ---
    mk("P008", "Trailblazer Adventure Touring Jacket", "Jackets", 380.00,
       "Waterproof textile adventure touring jacket with removable thermal liner and CE armor at shoulders and elbows.",
       ["adventure", "touring", "waterproof", "textile", "ce-armor"]),
    mk("P009", "Mesh Pro Summer Riding Jacket", "Jackets", 220.00,
       "High-airflow mesh summer jacket with breathable panels and impact protectors for hot-weather commuting.",
       ["mesh", "summer", "ventilated", "commuter"]),
    mk("P010", "Ironside Leather Cruiser Jacket", "Jackets", 410.00,
       "Heavyweight cowhide cruiser jacket with classic styling, zippered vents, and armor pockets.",
       ["leather", "cruiser", "classic", "armor"]),
    mk("P011", "Stormshield Waterproof Shell Jacket", "Jackets", 290.00,
       "Packable waterproof shell jacket with taped seams and hi-vis accents for all-weather riding.",
       ["waterproof", "shell", "hi-vis", "rain"]),
    mk("P012", "Retro Bomber Riding Jacket", "Jackets", 260.00,
       "Waxed-cotton retro bomber with a quilted liner and discreet CE armor for cafe and street riding.",
       ["retro", "bomber", "waxed-cotton", "cafe-racer"]),

    # --- Gloves ---
    mk("P013", "Gauntlet Pro Leather Gloves", "Gloves", 130.00,
       "Full-gauntlet leather gloves with carbon knuckle protection and touchscreen fingertips.",
       ["leather", "gauntlet", "carbon-knuckle", "touchscreen"]),
    mk("P014", "Summer Mesh Vented Gloves", "Gloves", 75.00,
       "Short-cuff ventilated mesh gloves with padded palms for hot-weather commuting.",
       ["mesh", "summer", "short-cuff", "ventilated"]),
    mk("P015", "Winter Thermal Waterproof Gloves", "Gloves", 110.00,
       "Insulated waterproof winter gloves with a windproof membrane and visor wipe.",
       ["winter", "waterproof", "thermal", "insulated"]),
    mk("P016", "Carbon Knuckle Short Gloves", "Gloves", 95.00,
       "Minimalist short leather gloves with carbon knuckle armor for street and cafe riding.",
       ["leather", "short", "carbon-knuckle", "street"]),
    mk("P017", "Touchscreen Commuter Gloves", "Gloves", 60.00,
       "Lightweight all-season commuter gloves with touchscreen-compatible fingertips.",
       ["commuter", "touchscreen", "all-season"]),

    # --- Boots ---
    mk("P018", "Apex Touring Waterproof Boots", "Boots", 260.00,
       "Tall waterproof touring boots with ankle armor and oil-resistant soles for long-distance comfort.",
       ["touring", "waterproof", "ankle-armor"]),
    mk("P019", "Adventure ADV Off-Road Boots", "Boots", 320.00,
       "Rugged ADV boots with shin plates and buckle closures for enduro and adventure riding.",
       ["adventure", "adv", "off-road", "enduro"]),
    mk("P020", "Street Sport Ankle Boots", "Boots", 180.00,
       "Low-cut sport riding shoes with reinforced toe box and grippy soles for urban riders.",
       ["street", "sport", "ankle", "urban"]),
    mk("P021", "Classic Engineer Leather Boots", "Boots", 230.00,
       "Timeless engineer-style leather boots with hidden ankle protection for cruiser and cafe riders.",
       ["leather", "engineer", "cruiser", "classic"]),

    # --- Pants ---
    mk("P022", "Kevlar Lined Riding Jeans", "Pants", 190.00,
       "Slim-fit riding jeans lined with DuPont Kevlar and removable knee and hip armor.",
       ["kevlar", "jeans", "armor", "casual"]),
    mk("P023", "Adventure Cargo Touring Pants", "Pants", 240.00,
       "Waterproof cargo touring pants with thermal liner and CE knee armor for all-day rides.",
       ["adventure", "touring", "waterproof", "cargo"]),
    mk("P024", "Leather Track Pants", "Pants", 350.00,
       "Perforated leather track pants with stretch panels and knee-slider attachment points.",
       ["leather", "track", "race", "perforated"], in_stock=False),  # SOLD OUT — drives alt scenario
    mk("P025", "Textile Waterproof Over-Pants", "Pants", 150.00,
       "Packable waterproof over-pants that slip over jeans for sudden downpours.",
       ["waterproof", "over-pants", "rain", "packable"]),

    # --- Accessories ---
    mk("P026", "Bluetooth Helmet Comm System", "Accessories", 200.00,
       "Helmet-mounted Bluetooth intercom with rider-to-rider comms, music, and voice navigation.",
       ["bluetooth", "comm", "intercom", "electronics"]),
    mk("P027", "Tank Bag 20L Magnetic", "Accessories", 110.00,
       "Expandable 20-liter magnetic tank bag with a clear phone-map window and rain cover.",
       ["luggage", "tank-bag", "magnetic", "touring"]),
    mk("P028", "Saddlebag Pannier Set", "Accessories", 280.00,
       "Pair of weatherproof throw-over saddlebags with quick-release mounts for touring storage.",
       ["luggage", "saddlebag", "pannier", "touring"], in_stock=False),
    mk("P029", "Back Protector CE Insert", "Accessories", 90.00,
       "CE level-2 back protector insert that slots into most riding jackets.",
       ["protection", "back-protector", "ce", "armor"]),
    mk("P030", "Chest Armor Insert Set", "Accessories", 70.00,
       "CE chest armor inserts to upgrade jacket impact protection.",
       ["protection", "chest-armor", "ce", "armor"]),
    mk("P031", "Knee Slider Pucks", "Accessories", 40.00,
       "Replaceable hook-and-loop knee sliders for track-day lean angles.",
       ["track", "knee-slider", "race"]),
    mk("P032", "Anti-Fog Pinlock Visor Insert", "Accessories", 35.00,
       "Pinlock anti-fog insert that keeps your visor clear in cold and wet conditions.",
       ["visor", "anti-fog", "pinlock"]),
    mk("P033", "Tinted Visor Shield", "Accessories", 55.00,
       "Smoke-tinted replacement visor shield for bright-day glare reduction.",
       ["visor", "tinted", "shield"]),
    mk("P034", "Riding Balaclava", "Accessories", 25.00,
       "Moisture-wicking balaclava that prevents helmet odor and adds warmth.",
       ["balaclava", "base-layer", "comfort"]),
    mk("P035", "Neck Tube Gaiter", "Accessories", 20.00,
       "Windproof neck tube gaiter to block drafts on cold rides.",
       ["neck-tube", "gaiter", "winter"]),
    mk("P036", "Reflective Hi-Vis Vest", "Accessories", 45.00,
       "Lightweight reflective hi-vis vest for low-light commuting visibility.",
       ["hi-vis", "reflective", "safety", "commuter"]),
    mk("P037", "Base Layer Compression Top", "Accessories", 65.00,
       "Moisture-wicking compression base layer for temperature regulation under gear.",
       ["base-layer", "compression", "comfort"]),
    mk("P038", "Heated Grips Kit", "Accessories", 130.00,
       "Universal heated grips kit with multiple heat settings for cold-weather riding.",
       ["heated-grips", "electronics", "winter"], in_stock=False),
    mk("P039", "Phone Mount Handlebar Pro", "Accessories", 50.00,
       "Vibration-dampening handlebar phone mount with a secure quick-lock cradle.",
       ["phone-mount", "handlebar", "navigation"]),
    mk("P040", "Tire Repair Plug Kit", "Accessories", 35.00,
       "Compact tubeless tire repair plug kit with CO2 inflators for roadside fixes.",
       ["tire-repair", "roadside", "tools"]),
    mk("P041", "Chain Lube and Clean Kit", "Accessories", 30.00,
       "Chain maintenance kit with cleaner, lube, and a grunge brush.",
       ["maintenance", "chain", "tools"]),
    mk("P042", "Bar End Mirrors Pair", "Accessories", 60.00,
       "Aluminum bar-end mirrors for a clean cafe-racer look and a wide rear view.",
       ["mirrors", "bar-end", "cafe-racer", "styling"]),
    mk("P043", "Frame Sliders Crash Protection", "Accessories", 120.00,
       "Bolt-on frame sliders that protect fairings and engine cases in a tip-over.",
       ["protection", "frame-sliders", "crash"]),
    mk("P044", "USB Charger Handlebar Mount", "Accessories", 40.00,
       "Weatherproof handlebar USB charger to keep your devices powered en route.",
       ["usb", "charger", "electronics"]),
    mk("P045", "Disc Lock Anti-Theft", "Accessories", 55.00,
       "Hardened disc lock with a reminder cable to deter theft when parked.",
       ["security", "disc-lock", "anti-theft"]),
    mk("P046", "Motorcycle Cover Waterproof", "Accessories", 70.00,
       "Breathable waterproof cover with heat-resistant panels and lock holes.",
       ["cover", "waterproof", "storage"]),
    mk("P047", "Ear Plugs Reusable 3-Pack", "Accessories", 20.00,
       "Reusable filtered ear plugs that cut wind noise while keeping you aware.",
       ["ear-plugs", "comfort", "safety"]),

    # --- Cafe-racer collection (new arrivals — supports latent-want re-engagement) ---
    mk("P048", "Cafe Racer Riding Gloves", "Gloves", 100.00,
       "Vintage-look perforated leather cafe racer gloves with low-profile knuckle protection.",
       ["cafe-racer", "leather", "vintage", "short"], created_days_ago=7),
    mk("P049", "Cafe Racer Ankle Boots", "Boots", 210.00,
       "Retro cafe-racer leather ankle boots with concealed ankle armor and a cap toe.",
       ["cafe-racer", "leather", "retro", "ankle"], created_days_ago=7),

    # --- New helmet drop (supports VIP win-back) ---
    mk("P050", "Aurora Sport Helmet", "Helmets", 300.00,
       "Newly released sport full-face helmet with a fresh colorway, optimized aero, and emergency cheek-pad release.",
       ["sport", "full-face", "new", "aero"], created_days_ago=4),
]

PROD = {p["product_id"]: p for p in PRODUCTS}
PRICE = {p["product_id"]: p["price"] for p in PRODUCTS}
PRODUCT_IDS = [p["product_id"] for p in PRODUCTS]


# ----------------------------------------------------------------------------
# Event / order / cart helpers
# ----------------------------------------------------------------------------
EVENTS = []
ORDERS = []
CARTS = []
_cart_seq = 1000


def add_event(cid, type_, ts, product_id=None, query=None, meta=None):
    doc = {"customer_id": cid, "type": type_, "ts": ts}
    if product_id is not None:
        doc["product_id"] = product_id
    if query is not None:
        doc["query"] = query
    if meta is not None:
        doc["metadata"] = meta
    EVENTS.append(doc)


def make_orders(cid, n, earliest, latest):
    """Generate n orders for a customer and log a matching 'order' event each."""
    made = []
    for _ in range(n):
        item_ids = random.sample(PRODUCT_IDS, k=random.randint(1, 3))
        items = [{"product_id": p, "price": PRICE[p], "qty": 1} for p in item_ids]
        total = round(sum(PRICE[p] for p in item_ids), 2)
        ts = rand_between(earliest, latest)
        order = {"customer_id": cid, "items": items, "total": total, "ts": ts}
        made.append(order)
        ORDERS.append(order)
        add_event(cid, "order", ts, product_id=item_ids[0],
                   meta={"total": total, "n_items": len(items)})
    return made


# Cart funnel stages, ordered by how close the shopper got to buying.
STAGE_INTENT = {"cart": 0.30, "checkout_started": 0.50, "payment_info": 0.70}


def add_abandoned_cart(cid, product_ids, abandoned_at, stage="checkout_started",
                       source="shopify", note=None):
    """
    Create an abandoned-cart document (the kind of payload a Shopify
    'checkouts/abandoned' webhook would deliver) plus the matching
    cart_add / checkout_start / cart_abandon behavior events.
    """
    global _cart_seq
    _cart_seq += 1
    cart_id = f"CART-{_cart_seq}"
    items = [{
        "product_id": pid,
        "title": PROD[pid]["title"],
        "price": PRICE[pid],
        "qty": 1,
        "in_stock_now": PROD[pid]["in_stock"],
    } for pid in product_ids]
    cart_value = round(sum(i["price"] for i in items), 2)

    cart_doc = {
        "cart_id": cart_id,
        "customer_id": cid,
        "source": source,                       # shopify | woocommerce | custom
        "stage": stage,                         # how far down the funnel
        "items": items,
        "cart_value": cart_value,
        "currency": "USD",
        "created_at": abandoned_at,             # when it was abandoned
        "checkout_url": f"https://morsegrid-demo.myshopify.com/cart/{cart_id}",
        "recovered": False,
        "recovery_status": "pending",           # pending | sent | recovered
    }
    if note:
        cart_doc["note"] = note
    CARTS.append(cart_doc)

    # Behavior trail leading up to the abandon
    for pid in product_ids:
        add_event(cid, "view", abandoned_at - timedelta(minutes=40), product_id=pid)
        add_event(cid, "cart_add", abandoned_at - timedelta(minutes=30),
                  product_id=pid, meta={"cart_id": cart_id})
    if stage in ("checkout_started", "payment_info"):
        add_event(cid, "checkout_start", abandoned_at - timedelta(minutes=12),
                  meta={"cart_id": cart_id, "cart_value": cart_value})
    add_event(cid, "cart_abandon", abandoned_at, product_id=product_ids[0],
              meta={"cart_id": cart_id, "cart_value": cart_value, "stage": stage})
    return cart_doc


SEARCH_TERMS = [
    "adventure touring helmet", "summer mesh gloves", "waterproof boots",
    "leather cafe racer jacket", "kevlar riding jeans", "bluetooth intercom",
    "tank bag luggage", "track race boots", "hi-vis vest", "heated grips",
]
INTERESTS = [
    "adventure touring gear", "cafe-racer street style", "track-day performance",
    "all-weather commuting", "cruiser classic looks",
]


def build_generic(cid, name, segment):
    created = days_ago(random.randint(120, 400))
    if segment == "VIP":
        n_orders = random.randint(4, 7); open_rate = round(random.uniform(0.55, 0.85), 2); last_active = days_ago(random.randint(4, 20))
    elif segment == "repeat":
        n_orders = random.randint(2, 4); open_rate = round(random.uniform(0.35, 0.65), 2); last_active = days_ago(random.randint(15, 50))
    elif segment == "one-time":
        n_orders = 1; open_rate = round(random.uniform(0.20, 0.50), 2); last_active = days_ago(random.randint(40, 95))
    elif segment == "cart-abandoner":
        n_orders = random.randint(0, 1); open_rate = round(random.uniform(0.30, 0.60), 2); last_active = days_ago(random.randint(1, 5))
    else:  # cold / dormant
        n_orders = random.randint(0, 1); open_rate = round(random.uniform(0.05, 0.35), 2); last_active = days_ago(random.randint(70, 160))

    sms_optin = random.random() < 0.6
    last5 = [random.random() < open_rate for _ in range(5)]

    cust_orders = make_orders(cid, n_orders, created, last_active)
    spend = round(sum(o["total"] for o in cust_orders), 2)

    for _ in range(random.randint(3, 6)):  # views
        add_event(cid, "view", rand_between(created, last_active), product_id=random.choice(PRODUCT_IDS))
    if random.random() < 0.5:  # search
        add_event(cid, "search", rand_between(created, last_active), query=random.choice(SEARCH_TERMS))
    for _ in range(random.randint(2, 4)):  # email engagement
        t = rand_between(last_active - timedelta(days=30), last_active)
        add_event(cid, "email_open" if random.random() < open_rate else "email_sent", t)

    # cart-abandoner generics get a real abandoned cart for queue depth
    if segment == "cart-abandoner":
        n_items = random.choice([1, 1, 2])
        pids = random.sample([p for p in PRODUCT_IDS if PROD[p]["in_stock"]], k=n_items)
        stage = random.choice(["cart", "checkout_started", "checkout_started", "payment_info"])
        add_abandoned_cart(cid, pids, hours_ago(random.randint(5, 70)), stage=stage)

    summary = (f"{segment} customer, {n_orders} orders (~${spend:.0f} lifetime), "
               f"email open rate {int(open_rate * 100)}%, last active {(NOW - last_active).days} days ago. "
               f"Interest: {random.choice(INTERESTS)}.")
    return {
        "customer_id": cid, "name": name, "email": f"{cid.lower()}@example.com",
        "phone": f"+1555{random.randint(1000000, 9999999)}",
        "ig_handle": "@" + name.lower().replace(" ", "_"),
        "segment": segment, "total_orders": n_orders, "total_spend": spend,
        "created_at": created, "last_active_at": last_active,
        "engagement": {"open_rate": open_rate, "click_rate": round(open_rate * 0.3, 2),
                       "sms_optin": sms_optin, "last5_opens": last5},
        "behavior_summary": summary,
    }


# ----------------------------------------------------------------------------
# 2. Hero personas — 3 abandoned-cart + 2 dormant re-engagement
# ----------------------------------------------------------------------------

# --- C001 Mike: high-value cart, reached payment, abandoned 3h ago (REASSURE) ---
mike = {
    "customer_id": "C001", "name": "Mike Henderson", "email": "mike.h.testapp@gmail.com",
    "phone": "+15550192", "ig_handle": "@mike_rides", "segment": "cart-abandoner",
    "created_at": days_ago(95), "last_active_at": hours_ago(3),
    "engagement": {"open_rate": 0.80, "click_rate": 0.40, "sms_optin": True,
                   "last5_opens": [True, True, False, True, True]},
    "behavior_summary": ("Reached the payment step on a $599 Apex Carbon Full-Face Helmet, then "
                         "abandoned the checkout 3 hours ago. High intent on premium track headgear; "
                         "highly email-responsive."),
}
# --- C002 Sarah: $700 two-item cart, 0/5 email opens -> SMS channel switch ---
sarah = {
    "customer_id": "C002", "name": "Sarah Jenkins", "email": "sarah.j.testapp@gmail.com",
    "phone": "+15558831", "ig_handle": "@sarah_moto", "segment": "cart-abandoner",
    "created_at": days_ago(120), "last_active_at": hours_ago(6),
    "engagement": {"open_rate": 0.05, "click_rate": 0.00, "sms_optin": True,
                   "last5_opens": [False, False, False, False, False]},
    "behavior_summary": ("Abandoned a $700 two-item adventure kit (Trailblazer touring jacket + ADV "
                         "boots) at checkout 6 hours ago. Has not opened any of the last 5 emails; "
                         "SMS opt-in is active."),
}
# --- C003 Diego: cart item now SOLD OUT -> suggest in-stock alternatives ---
diego = {
    "customer_id": "C003", "name": "Diego Alvarez", "email": "diego.a.testapp@gmail.com",
    "phone": "+15559923", "ig_handle": "@diego_customs", "segment": "cart-abandoner",
    "created_at": days_ago(70), "last_active_at": hours_ago(28),
    "engagement": {"open_rate": 0.70, "click_rate": 0.35, "sms_optin": False,
                   "last5_opens": [True, False, True, True, False]},
    "behavior_summary": ("Added the Leather Track Pants to cart yesterday, then abandoned at the cart "
                         "stage. That exact item has since sold out — needs strong in-stock "
                         "alternatives. High email engagement."),
}
# --- C004 Ava: VIP gone quiet 78 days -> win-back tied to a new arrival ---
ava = {
    "customer_id": "C004", "name": "Ava Thompson", "email": "ava.t.testapp@gmail.com",
    "phone": "+15557741", "ig_handle": "@ava_adv", "segment": "dormant_vip",
    "created_at": days_ago(420), "last_active_at": days_ago(78),
    "engagement": {"open_rate": 0.55, "click_rate": 0.25, "sms_optin": False,
                   "last5_opens": [True, False, False, True, False]},
    "behavior_summary": ("VIP with 4 lifetime orders (~$1,450) who has been quiet for 78 days. "
                         "Consistently buys premium sport and full-face helmets. The new Aurora Sport "
                         "Helmet just dropped this week."),
}
# --- C005 Marcus: latent want -> searched cafe racer jacket long ago, in stock now ---
marcus = {
    "customer_id": "C005", "name": "Marcus Webb", "email": "marcus.w.testapp@gmail.com",
    "phone": "+15553360", "ig_handle": "@marcus_caferacer", "segment": "dormant_email",
    "created_at": days_ago(140), "last_active_at": days_ago(50),
    "engagement": {"open_rate": 0.45, "click_rate": 0.20, "sms_optin": True,
                   "last5_opens": [True, False, True, False, False]},
    "behavior_summary": ("Searched for a 'vintage cafe racer jacket' ~50 days ago when none were in "
                         "stock, then went quiet. The Classic Leather Cafe Racer Jacket arrived a week "
                         "ago. Moderate email engagement; SMS opt-in active."),
}

HEROES = [mike, sarah, diego, ava, marcus]
HERO_CART_IDS = ["C001", "C002", "C003"]
HERO_DORMANT_IDS = ["C004", "C005"]

# Hero lifetime orders (gives them realistic spend history)
for cust, n in [(mike, 1), (sarah, 1), (diego, 2), (ava, 4), (marcus, 1)]:
    co = make_orders(cust["customer_id"], n, cust["created_at"],
                     cust["last_active_at"] if cust["customer_id"] in HERO_DORMANT_IDS
                     else cust["created_at"] + timedelta(days=20))
    cust["total_orders"] = len(co)
    cust["total_spend"] = round(sum(o["total"] for o in co), 2)

# --- Hero abandoned carts ---
# C001 — single premium item, reached payment, 3h ago
add_abandoned_cart("C001", ["P002"], hours_ago(3), stage="payment_info",
                   note="High-value single item; shopper reached the payment step.")
# C002 — two-item adventure kit, checkout started, 6h ago
add_abandoned_cart("C002", ["P008", "P019"], hours_ago(6), stage="checkout_started",
                   note="Two-item kit; email-unresponsive, SMS opt-in active.")
# C003 — leather track pants (now sold out), cart stage, ~28h ago
add_abandoned_cart("C003", ["P024"], hours_ago(28), stage="cart",
                   note="Item sold out after abandon; needs in-stock alternatives.")

# --- Hero dormant signals (re-engagement, no cart) ---
# C004 Ava — past sport-helmet affinity + recent open
add_event("C004", "view", days_ago(120), product_id="P002")
add_event("C004", "view", days_ago(110), product_id="P007")
add_event("C004", "search", days_ago(118), query="lightweight sport full-face helmet")
add_event("C004", "email_open", days_ago(82))
# C005 Marcus — the latent want
add_event("C005", "search", days_ago(50), query="vintage cafe racer jacket leather")
add_event("C005", "view", days_ago(50), product_id="P010")
add_event("C005", "view", days_ago(50), product_id="P012")
add_event("C005", "email_open", days_ago(48))


# ----------------------------------------------------------------------------
# 3. Generic customers (queue depth + a few more abandoned carts)
# ----------------------------------------------------------------------------
GENERIC = [
    ("C006", "Liam Carter", "VIP"),
    ("C007", "Noah Bennett", "repeat"),
    ("C008", "Emma Davis", "repeat"),
    ("C009", "Olivia Wright", "repeat"),
    ("C010", "James Cole", "one-time"),
    ("C011", "Sophia Reed", "one-time"),
    ("C012", "Lucas Gray", "cart-abandoner"),
    ("C013", "Mia Foster", "cart-abandoner"),
    ("C014", "Ethan Ward", "cart-abandoner"),
    ("C015", "Isabella King", "cold"),
    ("C016", "Mason Hughes", "cold"),
    ("C017", "Charlotte Bell", "cold"),
    ("C018", "Benjamin Ross", "repeat"),
]

CUSTOMERS = HEROES + [build_generic(cid, name, seg) for cid, name, seg in GENERIC]


# ----------------------------------------------------------------------------
# 4. Seed
# ----------------------------------------------------------------------------
def seed_database():
    client = get_db_client()
    if not client:
        print("ERROR: Could not connect to database for seeding.")
        return

    db = client["morsegrid_outfitters"]
    print("Starting clean database seeding...")
    for c in ["products", "customers", "behavior_events", "orders",
              "abandoned_carts", "messages_sent"]:
        db[c].drop()

    db.products.insert_many(PRODUCTS)
    print(f"OK - products:        {len(PRODUCTS)}")
    db.customers.insert_many(CUSTOMERS)
    print(f"OK - customers:       {len(CUSTOMERS)}")
    if ORDERS:
        db.orders.insert_many(ORDERS)
    print(f"OK - orders:          {len(ORDERS)}")
    db.behavior_events.insert_many(EVENTS)
    print(f"OK - behavior_events: {len(EVENTS)}")
    db.abandoned_carts.insert_many(CARTS)
    print(f"OK - abandoned_carts: {len(CARTS)}  "
          f"(value ${sum(c['cart_value'] for c in CARTS):,.0f})")
    print("DONE - seeding complete. Vectors NOT set yet -> run data/build_index.py next.")
    client.close()


if __name__ == "__main__":
    seed_database()
