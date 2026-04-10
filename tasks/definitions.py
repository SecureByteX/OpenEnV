"""
tasks/definitions.py
Three task definitions with injected defects and ground truth.

Grader matching rules:
  - abs(comment.line - issue["line"]) <= 3   (line proximity)
  - any keyword from issue["keywords"] in comment.message (case-insensitive)
"""
from typing import Any, Dict


# ---------------------------------------------------------------------------
# TASK 1 - Easy: Simple Bug Detection
# ---------------------------------------------------------------------------
# File content as a plain string (line numbers annotated in comments)
_T1 = (
    "def compute_average(numbers):\n"                              # 1
    '    """Return the average of a list of numbers."""\n'         # 2
    "    total = 0\n"                                              # 3
    "    for n in numbers:\n"                                      # 4
    "        total += n\n"                                         # 5
    "    return total / len(numbers)  # BUG-1: ZeroDivisionError when empty\n"  # 6
    "\n"                                                           # 7
    "\n"                                                           # 8
    "def find_duplicates(items):\n"                                # 9
    '    """Return items that appear more than once."""\n'         # 10
    "    seen = {}\n"                                              # 11
    "    duplicates = []\n"                                        # 12
    "    for item in items:\n"                                     # 13
    "        if item in seen:\n"                                   # 14
    "            duplicates.append(item)\n"                        # 15
    "        seen[item] = True\n"                                  # 16
    "    return duplicates  # BUG-2: appends every extra occurrence (3+ times wrong)\n"  # 17
    "\n"                                                           # 18
    "\n"                                                           # 19
    "def safe_divide(a, b):\n"                                     # 20
    '    """Divide a by b, returning None if b is zero."""\n'      # 21
    "    if b = 0:  # BUG-3: SyntaxError - assignment instead of comparison\n"  # 22
    "        return None\n"                                        # 23
    "    return a / b\n"                                           # 24
    "\n"                                                           # 25
    "\n"                                                           # 26
    "def flatten(nested):\n"                                       # 27
    '    """Flatten one level of nesting."""\n'                    # 28
    "    result = []\n"                                            # 29
    "    for sublist in nested:\n"                                 # 30
    "        result.extend(sublist)\n"                             # 31
    "    return result\n"                                          # 32
)

TASK_SIMPLE_BUG: Dict[str, Any] = {
    "name": "simple-bug-detection",
    "difficulty": "easy",
    "max_steps": 10,
    "pr_title": "Add utility functions for list processing",
    "pr_description": (
        "Adds three helper utilities used across the analytics module: "
        "compute_average(), find_duplicates(), and safe_divide(). "
        "Also includes flatten() for one-level list flattening."
    ),
    "files": [
        {
            "filename": "utils/list_helpers.py",
            "language": "python",
            "content": _T1,
            "diff": (
                "+def compute_average(numbers):\n"
                "+    return total / len(numbers)\n"
                "+def find_duplicates(items):\n"
                "+    return duplicates\n"
                "+def safe_divide(a, b):\n"
                "+    if b = 0:\n"
                "+        return None\n"
            ),
            "line_count": 32,
        }
    ],
    "ground_truth_bugs": [
        {
            "id": "bug-1",
            "filename": "utils/list_helpers.py",
            "line": 6,
            "description": "ZeroDivisionError when numbers is an empty list",
            "keywords": ["zero", "empty", "division", "len", "average", "divide"],
        },
        {
            "id": "bug-2",
            "filename": "utils/list_helpers.py",
            "line": 17,
            "description": "find_duplicates appends every extra occurrence, wrong for 3+ times",
            "keywords": ["duplicate", "multiple", "3+", "three", "set", "seen", "append", "count"],
        },
        {
            "id": "bug-3",
            "filename": "utils/list_helpers.py",
            "line": 22,
            "description": "SyntaxError: assignment = used instead of comparison ==",
            "keywords": ["syntax", "assignment", "==", "comparison", "operator", "equal"],
        },
    ],
    "ground_truth_security": [],
    "ground_truth_style": [
        {
            "id": "style-1",
            "filename": "utils/list_helpers.py",
            "line": 1,
            "description": "Missing type hints on function signatures",
            "keywords": ["type", "hint", "annotation", "typing"],
        },
    ],
}


# ---------------------------------------------------------------------------
# TASK 2 - Medium: Security Audit
# ---------------------------------------------------------------------------
_T2 = (
    "import sqlite3\n"                                             # 1
    "import jwt\n"                                                 # 2
    "import hashlib\n"                                             # 3
    "from flask import request, jsonify\n"                         # 4
    "\n"                                                           # 5
    'SECRET_KEY = "supersecret123"  # SEC-1: hardcoded secret\n'  # 6
    "\n"                                                           # 7
    "\n"                                                           # 8
    "def login():\n"                                               # 9
    '    """Authenticate user and return JWT token."""\n'          # 10
    '    username = request.json.get("username")\n'               # 11
    '    password = request.json.get("password")\n'               # 12
    "\n"                                                           # 13
    "    # Hash the password before lookup\n"                      # 14
    "    hashed = hashlib.md5(password.encode()).hexdigest()"      # 15
    "  # SEC-2: MD5 broken\n"
    "\n"                                                           # 16
    '    conn = sqlite3.connect("users.db")\n'                    # 17
    "    cursor = conn.cursor()\n"                                 # 18
    "\n"                                                           # 19
    "    # SEC-3: SQL injection via f-string\n"                   # 20
    "    query = f\"SELECT * FROM users WHERE username='{username}'"  # 21
    " AND password='{hashed}'\"\n"
    "    cursor.execute(query)\n"                                  # 22
    "    user = cursor.fetchone()\n"                               # 23
    "    conn.close()\n"                                           # 24
    "\n"                                                           # 25
    "    if not user:\n"                                           # 26
    '        return jsonify({"error": "Invalid credentials"}), 401\n'  # 27
    "\n"                                                           # 28
    "    token = jwt.encode(\n"                                    # 29
    '        {"user_id": user[0], "username": username},\n'       # 30
    "        SECRET_KEY,\n"                                        # 31
    '        algorithm="HS256"\n'                                  # 32
    "    )\n"                                                      # 33
    '    return jsonify({"token": token}), 200\n'                  # 34
    "\n"                                                           # 35
    "\n"                                                           # 36
    "def update_profile():\n"                                      # 37
    '    """Update display name and bio."""\n'                     # 38
    '    token = request.headers.get("Authorization", "")'        # 39
    '.replace("Bearer ", "")\n'
    "\n"                                                           # 40
    "    try:\n"                                                   # 41
    "        payload = jwt.decode(token, SECRET_KEY,"              # 42
    ' algorithms=["HS256"])\n'
    "    except Exception:\n"                                      # 43
    '        return jsonify({"error": "Invalid token"}), 401\n'   # 44
    "\n"                                                           # 45
    '    user_id = payload["user_id"]\n'                          # 46
    '    display_name = request.json.get("display_name", "")\n'   # 47
    '    bio = request.json.get("bio", "")\n'                     # 48
    "\n"                                                           # 49
    "    # BUG-4: no length validation - DoS vector\n"            # 50
    '    conn = sqlite3.connect("users.db")\n'                    # 51
    "    cursor = conn.cursor()\n"                                 # 52
    "    cursor.execute(\n"                                        # 53
    '        "UPDATE users SET display_name=?, bio=? WHERE id=?",\n'  # 54
    "        (display_name, bio, user_id)\n"                      # 55
    "    )\n"                                                      # 56
    "    conn.commit()\n"                                          # 57
    "    conn.close()\n"                                           # 58
    '    return jsonify({"status": "updated"}), 200\n'            # 59
)

TASK_SECURITY_AUDIT: Dict[str, Any] = {
    "name": "security-audit",
    "difficulty": "medium",
    "max_steps": 15,
    "pr_title": "Add user authentication endpoint and profile update API",
    "pr_description": (
        "Implements POST /login with JWT token generation and "
        "POST /profile/update for changing display name and bio. "
        "Passwords are hashed before storage. SQLite stores user data."
    ),
    "files": [
        {
            "filename": "api/auth.py",
            "language": "python",
            "content": _T2,
            "diff": (
                "+SECRET_KEY = 'supersecret123'\n"
                "+hashed = hashlib.md5(password.encode()).hexdigest()\n"
                "+query = f\"SELECT * FROM users WHERE username='{username}'\"\n"
                "+cursor.execute(query)\n"
                "+display_name = request.json.get('display_name', '')\n"
            ),
            "line_count": 59,
        }
    ],
    "ground_truth_bugs": [
        {
            "id": "bug-4",
            "filename": "api/auth.py",
            "line": 50,
            "description": "No input length validation on display_name/bio - DoS vector",
            "keywords": ["length", "limit", "validation", "dos", "input", "size", "max", "truncate"],
        },
    ],
    "ground_truth_security": [
        {
            "id": "sec-1",
            "filename": "api/auth.py",
            "line": 6,
            "description": "Hardcoded JWT secret key - must use os.environ",
            "keywords": ["hardcoded", "secret", "key", "environ", "env", "variable", "os.environ"],
        },
        {
            "id": "sec-2",
            "filename": "api/auth.py",
            "line": 15,
            "description": "MD5 is cryptographically broken for passwords - use bcrypt or argon2",
            "keywords": ["md5", "bcrypt", "argon", "scrypt", "password", "hash", "broken", "weak"],
        },
        {
            "id": "sec-3",
            "filename": "api/auth.py",
            "line": 21,
            "description": "SQL injection via f-string interpolation - use parameterized queries",
            "keywords": ["sql", "injection", "f-string", "parameterized", "interpolation", "format"],
        },
    ],
    "ground_truth_style": [],
}


# ---------------------------------------------------------------------------
# TASK 3 - Hard: Architecture Review
# ---------------------------------------------------------------------------
_T3 = (
    "import redis\n"                                               # 1
    "import json\n"                                                # 2
    "import time\n"                                                # 3
    "import threading\n"                                           # 4
    "from typing import List, Dict, Optional\n"                    # 5
    "\n"                                                           # 6
    "_redis = redis.Redis(host='localhost', port=6379)\n"          # 7
    "_cache: dict = {}  # ARCH-1: unbounded - memory leak\n"      # 8
    "\n"                                                           # 9
    "RETRY_LIMIT = 3\n"                                            # 10
    "\n"                                                           # 11
    "\n"                                                           # 12
    "def get_product(product_id: str) -> Optional[Dict]:\n"       # 13
    '    """Fetch product from cache, Redis, or DB."""\n'          # 14
    "    if product_id in _cache:\n"                               # 15
    "        return _cache[product_id]\n"                          # 16
    "\n"                                                           # 17
    "    cached = _redis.get(f'product:{product_id}')\n"          # 18
    "    if cached:\n"                                             # 19
    "        product = json.loads(cached)\n"                       # 20
    "        _cache[product_id] = product  # never evicted\n"     # 21
    "        return product\n"                                     # 22
    "\n"                                                           # 23
    "    product = _fetch_from_db(product_id)\n"                  # 24
    "    if product:\n"                                            # 25
    "        _redis.set(f'product:{product_id}', json.dumps(product))\n"  # 26
    "        _cache[product_id] = product\n"                       # 27
    "    return product\n"                                         # 28
    "\n"                                                           # 29
    "\n"                                                           # 30
    "def _fetch_from_db(product_id: str) -> Optional[Dict]:\n"   # 31
    '    """Simulated DB fetch."""\n'                              # 32
    "    time.sleep(0.05)\n"                                       # 33
    "    return {'id': product_id, 'name': 'Widget', 'price': 9.99, 'stock': 100}\n"  # 34
    "\n"                                                           # 35
    "\n"                                                           # 36
    "def process_order(order: Dict) -> Dict:\n"                   # 37
    '    """Process one order: validate, deduct stock, charge."""\n'  # 38
    "    results = []\n"                                           # 39
    "    total = 0\n"                                              # 40
    "\n"                                                           # 41
    "    for item in order['items']:\n"                           # 42
    "        product = get_product(item['product_id'])\n"         # 43
    "        if product is None:\n"                                # 44
    "            return {'status': 'error', 'message': 'not found'}\n"  # 45
    "\n"                                                           # 46
    "        if product['stock'] < item['quantity']:\n"           # 47
    "            return {'status': 'error', 'message': 'no stock'}\n"  # 48
    "\n"                                                           # 49
    "        # BUG-5: race condition - not atomic\n"              # 50
    "        product['stock'] -= item['quantity']\n"              # 51
    "        _redis.set(f\"product:{product['id']}\", json.dumps(product))\n"  # 52
    "\n"                                                           # 53
    "        line_total = product['price'] * item['quantity']\n"  # 54
    "        total += line_total\n"                                # 55
    "        results.append({'product_id': item['product_id'], 'line_total': line_total})\n"  # 56
    "\n"                                                           # 57
    "    for attempt in range(RETRY_LIMIT):\n"                    # 58
    "        success = _charge_payment(order['user_id'], total)\n"  # 59
    "        if success:\n"                                        # 60
    "            break\n"                                          # 61
    "        time.sleep(2 ** attempt)  # ARCH-2: blocks thread\n"  # 62
    "    else:\n"                                                  # 63
    "        # BUG-6: no rollback - inventory corrupted\n"        # 64
    "        return {'status': 'error', 'message': 'payment failed'}\n"  # 65
    "\n"                                                           # 66
    "    return {'status': 'ok', 'total': total, 'items': results}\n"  # 67
    "\n"                                                           # 68
    "\n"                                                           # 69
    "def _charge_payment(user_id: str, amount: float) -> bool:\n"  # 70
    "    import random\n"                                          # 71
    "    return random.random() > 0.2\n"                          # 72
    "\n"                                                           # 73
    "\n"                                                           # 74
    "def batch_process(orders: List[Dict]) -> List[Dict]:\n"      # 75
    '    """Process multiple orders concurrently."""\n'            # 76
    "    threads = []\n"                                           # 77
    "    results = []  # BUG-7: shared list - data race\n"        # 78
    "\n"                                                           # 79
    "    for order in orders:\n"                                   # 80
    "        t = threading.Thread(\n"                             # 81
    "            target=lambda o: results.append(process_order(o)),\n"  # 82
    "            args=(order,)\n"                                  # 83
    "        )\n"                                                  # 84
    "        threads.append(t)\n"                                  # 85
    "        t.start()\n"                                          # 86
    "\n"                                                           # 87
    "    for t in threads:\n"                                      # 88
    "        t.join()\n"                                           # 89
    "\n"                                                           # 90
    "    return results\n"                                         # 91
)

TASK_ARCHITECTURE_REVIEW: Dict[str, Any] = {
    "name": "architecture-review",
    "difficulty": "hard",
    "max_steps": 20,
    "pr_title": "Refactor order processing pipeline with Redis cache and concurrent batch support",
    "pr_description": (
        "Major refactor: adds Redis caching for product lookups, introduces concurrent "
        "batch processing via threading, adds exponential-backoff retry for payment failures. "
        "Please review for correctness, thread safety, and production readiness."
    ),
    "files": [
        {
            "filename": "orders/processor.py",
            "language": "python",
            "content": _T3,
            "diff": (
                "+_cache: dict = {}\n"
                "+_cache[product_id] = product  # never evicted\n"
                "+product['stock'] -= item['quantity']  # no lock\n"
                "+time.sleep(2 ** attempt)  # blocks thread\n"
                "+results = []  # shared, no lock\n"
                "+results.append(process_order(o))\n"
            ),
            "line_count": 91,
        }
    ],
    "ground_truth_bugs": [
        {
            "id": "bug-5",
            "filename": "orders/processor.py",
            "line": 51,
            "description": "Race condition: stock read-modify-write not atomic, concurrent orders oversell",
            "keywords": ["race", "condition", "atomic", "concurrent", "lock", "stock", "oversell", "thread"],
        },
        {
            "id": "bug-6",
            "filename": "orders/processor.py",
            "line": 64,
            "description": "No rollback when payment fails, stock already deducted, inventory corrupted",
            "keywords": ["rollback", "payment", "stock", "revert", "failure", "inventory", "compensat"],
        },
        {
            "id": "bug-7",
            "filename": "orders/processor.py",
            "line": 78,
            "description": "Thread-unsafe: shared results list mutated concurrently without a lock",
            "keywords": ["thread", "lock", "concurrent", "race", "unsafe", "results", "append", "mutex"],
        },
    ],
    "ground_truth_security": [],
    "ground_truth_style": [
        {
            "id": "arch-1",
            "filename": "orders/processor.py",
            "line": 8,
            "description": "Unbounded _cache dict causes memory leak, use LRU cache",
            "keywords": ["memory", "leak", "cache", "unbounded", "lru", "eviction", "bounded"],
        },
        {
            "id": "arch-2",
            "filename": "orders/processor.py",
            "line": 62,
            "description": "Blocking time.sleep in retry loop stalls thread pool worker",
            "keywords": ["blocking", "backoff", "sleep", "stall", "retry", "thread", "pool", "async"],
        },
    ],
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
TASKS: Dict[str, Any] = {
    "simple-bug-detection": TASK_SIMPLE_BUG,
    "security-audit": TASK_SECURITY_AUDIT,
    "architecture-review": TASK_ARCHITECTURE_REVIEW,
}


def get_task(name: str) -> Dict[str, Any]:
    if name not in TASKS:
        raise ValueError(
            f"Unknown task '{name}'. Available: {list(TASKS.keys())}"
        )
    return TASKS[name]
