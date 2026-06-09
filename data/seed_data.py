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
    # --- Hero products for the 3 demo scenarios ---
    mk("P001", "Rallye Adventure Helmet", "Helmets", 350.00,
       "Dual-sport adventure helmet with drop-down sun visor and an ultra-wide field of view. Premium aerodynamics for long dual-sport and off-road touring.",
       ["adventure", "dual-sport", "touring", "off-road", "sun-visor"],
       cost=150.00, created_days_ago=300, restocked_days_ago=2),  # scenario 1: back in stock
    mk("P002", "Apex Carbon Full-Face Helmet", "Helmets", 599.00,
       "Ultra-lightweight aerospace carbon-fiber shell with maximum track ventilation and an optically correct race shield.",
       ["carbon", "full-face", "track", "race", "lightweight"], cost=250.00, created_days_ago=200),
    mk("P003", "Classic Leather Cafe Racer Jacket", "Jackets", 450.00,
       "Premium top-grain cowhide cafe racer jacket with CE armor inserts and a vintage distressed finish.",
       ["cafe-racer", "leather", "vintage", "ce-armor", "retro"],
       cost=180.00, created_days_ago=7),  # scenario 3: new arrival

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
       ["leather", "track", "race", "perforated"], in_stock=False),
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

    # --- Cafe-racer collection (supports scenario 3 cross-sell) ---
    mk("P048", "Cafe Racer Riding Gloves", "Gloves", 100.00,
       "Vintage-look perforated leather cafe racer gloves with low-profile knuckle protection.",
       ["cafe-racer", "leather", "vintage", "short"], created_days_ago=7),
    mk("P049", "Cafe Racer Ankle Boots", "Boots", 210.00,
       "Retro cafe-racer leather ankle boots with concealed ankle armor and a cap toe.",
       ["cafe-racer", "leather", "retro", "ankle"], created_days_ago=7),

    # --- New helmet drop (supports scenario 2 channel-switch) ---
    mk("P050", "Aurora Sport Helmet", "Helmets", 300.00,
       "Newly released sport full-face helmet with a fresh colorway, optimized aero, and emergency cheek-pad release.",
       ["sport", "full-face", "new", "aero"], created_days_ago=4),
]

PRICE = {p["product_id"]: p["price"] for p in PRODUCTS}
PRODUCT_IDS = [p["product_id"] for p in PRODUCTS]


# ----------------------------------------------------------------------------
# Event / order helpers
# ----------------------------------------------------------------------------
EVENTS = []
ORDERS = []


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
        n_orders = 0; open_rate = round(random.uniform(0.30, 0.60), 2); last_active = days_ago(random.randint(2, 12))
    else:  # cold
        n_orders = 0; open_rate = round(random.uniform(0.05, 0.35), 2); last_active = days_ago(random.randint(70, 160))

    sms_optin = random.random() < 0.6
    last5 = [random.random() < open_rate for _ in range(5)]

    cust_orders = make_orders(cid, n_orders, created, last_active)
    spend = round(sum(o["total"] for o in cust_orders), 2)

    for _ in range(random.randint(3, 6)):  # views
        add_event(cid, "view", rand_between(created, last_active), product_id=random.choice(PRODUCT_IDS))
    if random.random() < 0.5:  # search
        add_event(cid, "search", rand_between(created, last_active), query=random.choice(SEARCH_TERMS))
    pairs = 2 if segment == "cart-abandoner" else (1 if random.random() < 0.3 else 0)  # cart abandons
    for _ in range(pairs):
        pid = random.choice(PRODUCT_IDS)
        t = rand_between(last_active - timedelta(days=4), last_active)
        add_event(cid, "cart_add", t, product_id=pid)
        add_event(cid, "cart_abandon", t + timedelta(minutes=18), product_id=pid)
    for _ in range(random.randint(2, 4)):  # email engagement
        t = rand_between(last_active - timedelta(days=30), last_active)
        add_event(cid, "email_open" if random.random() < open_rate else "email_sent", t)

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
# 2. Customers — 3 hero personas + 15 generics
# ----------------------------------------------------------------------------
mike = {
    "customer_id": "C001", "name": "Mike Henderson", "email": "mike.h.testapp@gmail.com",
    "phone": "+15550192", "ig_handle": "@mike_rides", "segment": "engaged",
    "total_orders": 0, "total_spend": 0.0,
    "created_at": days_ago(90), "last_active_at": days_ago(2),
    "engagement": {"open_rate": 0.85, "click_rate": 0.40, "sms_optin": True, "last5_opens": [True, True, False, True, True]},
    "behavior_summary": "Inquired explicitly about the Rallye Adventure Helmet via the chat widget when it was flagged out of stock. Prefers premium adventure headgear.",
}
sarah = {
    "customer_id": "C002", "name": "Sarah Jenkins", "email": "sarah.j.testapp@gmail.com",
    "phone": "+15558831", "ig_handle": "@sarah_moto", "segment": "dormant_email",
    "total_orders": 0, "total_spend": 0.0,
    "created_at": days_ago(120), "last_active_at": days_ago(14),
    "engagement": {"open_rate": 0.05, "click_rate": 0.00, "sms_optin": True, "last5_opens": [False, False, False, False, False]},
    "behavior_summary": "Browsed high-end carbon and sport helmets heavily two weeks ago but has ignored the last 5 broadcast marketing emails. SMS opt-in is active.",
}
diego = {
    "customer_id": "C003", "name": "Diego Alvarez", "email": "diego.a.testapp@gmail.com",
    "phone": "+15559923", "ig_handle": "@diego_customs", "segment": "engaged",
    "total_orders": 0, "total_spend": 0.0,
    "created_at": days_ago(60), "last_active_at": days_ago(4),
    "engagement": {"open_rate": 0.70, "click_rate": 0.35, "sms_optin": False, "last5_opens": [True, False, True, True, False]},
    "behavior_summary": "Searched for a 'cafe racer jacket' six weeks ago when none were in inventory. High email engagement; not opted into SMS.",
}

HEROES = [mike, sarah, diego]

# Hero orders (derive total_orders/total_spend from generated orders for consistency)
for cust, n in [(mike, 2), (sarah, 1), (diego, 3)]:
    co = make_orders(cust["customer_id"], n, cust["created_at"], cust["last_active_at"])
    cust["total_orders"] = len(co)
    cust["total_spend"] = round(sum(o["total"] for o in co), 2)

# Scenario-critical events
# Scenario 1 — Mike asked about an out-of-stock helmet that is now restocked
add_event("C001", "chat", days_ago(60), product_id="P001",
          query="Is the Rallye Adventure Helmet coming back in stock soon?")
add_event("C001", "view", days_ago(60), product_id="P001")
add_event("C001", "email_open", days_ago(8))
# Scenario 2 — Sarah browses helmets but ignores email (5 sent, 0 opened)
add_event("C002", "view", days_ago(14), product_id="P002")
add_event("C002", "view", days_ago(13), product_id="P050")
add_event("C002", "view", days_ago(12), product_id="P004")
for d in [20, 15, 11, 7, 3]:
    add_event("C002", "email_sent", days_ago(d))
# Scenario 3 — Diego searched for a cafe racer jacket 6 weeks ago; none existed then
add_event("C003", "search", days_ago(42), query="vintage cafe racer jacket leather")
add_event("C003", "view", days_ago(42), product_id="P010")
add_event("C003", "view", days_ago(42), product_id="P012")
add_event("C003", "email_open", days_ago(5))

GENERIC = [
    ("C004", "Ava Thompson", "VIP"),
    ("C005", "Liam Carter", "VIP"),
    ("C006", "Noah Bennett", "repeat"),
    ("C007", "Emma Davis", "repeat"),
    ("C008", "Olivia Wright", "repeat"),
    ("C009", "James Cole", "one-time"),
    ("C010", "Sophia Reed", "one-time"),
    ("C011", "Lucas Gray", "cart-abandoner"),
    ("C012", "Mia Foster", "cart-abandoner"),
    ("C013", "Ethan Ward", "cart-abandoner"),
    ("C014", "Isabella King", "cold"),
    ("C015", "Mason Hughes", "cold"),
    ("C016", "Charlotte Bell", "cold"),
    ("C017", "Benjamin Ross", "repeat"),
    ("C018", "Amelia Price", "one-time"),
]

CUSTOMERS = HEROES + [build_generic(cid, name, seg) for cid, name, seg in GENERIC]


# ----------------------------------------------------------------------------
# 3. Seed
# ----------------------------------------------------------------------------
def seed_database():
    client = get_db_client()
    if not client:
        print("ERROR: Could not connect to database for seeding.")
        return

    db = client["morsegrid_outfitters"]
    print("Starting clean database seeding...")
    for c in ["products", "customers", "behavior_events", "orders", "messages_sent"]:
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
    print("DONE - seeding complete. Vectors NOT set yet -> run data/build_index.py next.")
    client.close()


if __name__ == "__main__":
    seed_database()
