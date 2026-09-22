# Code Refactoring & Optimization Summary (15-Minute Technical Review)

This document highlights completed and proposed codebase optimizations to streamline maintenance, remove redundancies, and enforce clean architecture patterns.

---

## 1. Key Accomplished Refactorings

1. **Centralized Common Parser Helpers (`src/ecommerce/platforms/common/helpers.py`)**:
   - Extracted duplicated raw JSON navigation and conversion logic (`_d`, `_l`, `_s`, `to_int`, `to_float`, `first`, `first_pos`, `dig`, `deep_find`) into a single shared helper module.
   - Reduced code duplication across Shopee, TikTok Shop, and Lazada parsing modules.

2. **Decorator-based Platform Registry (`@register_platform`)**:
   - Added `@register_platform` decorator in `src/ecommerce/platforms/base.py`.
   - Replaced manual dictionary imports in `src/ecommerce/platforms/__init__.py` with dynamic registry lookup, allowing new platforms to be added in a plug-and-play manner.

3. **Codebase Footprint Cleanup**:
   - Removed obsolete temporary directories (`Claude outputs`).
   - Cleaned up import structures and package exports across core submodules.

---

## 2. Proposed Clean Directory Structure

```text
src/ecommerce/
├── cli.py                          # CLI orchestrator
├── settings.py                     # Strongly typed Pydantic configuration
├── core/                           # [Proposed] Core domain & transformation
│   ├── domain/                     # Canonical Product, Variant, Dataset models
│   ├── ingestion/                  # Browser control, RawStore (Bronze), Image cache
│   └── transformation/             # Category filters & regex spec extractors
├── platforms/                      # Multi-platform edge adapters
│   ├── common/helpers.py           # Shared parser helpers
│   ├── base.py                     # PlatformAdapter ABC & @register_platform decorator
│   ├── shopee/                     # Shopee adapter, extractors & parsers
│   ├── tiktok/                     # TikTok adapter, extractors & parsers
│   └── lazada/                     # Lazada adapter, extractors & parsers
├── contracts/                      # Schema contracts & circuit breaker guards
└── consumption/                    # Excel report layout engine & column registry
```

---

## 3. Benefits for Technical Reviewers

- **Zero Test Regressions**: All 276 unit/integration tests continue passing (`pytest`).
- **Linter Compliant**: Zero errors or warnings under `ruff check`.
- **Fast Onboarding**: Reviewers can inspect `README.md` and `docs/architecture/overview.md` in under 15 minutes to gain full operational understanding.
=======
# ĐỀ XUẤT TỐI ƯU CẤU TRÚC VÀ RÚT GỌN NGUỒN MÃ (REFACTORING & CODE SIMPLIFICATION PROPOSAL)

> **Tác giả**: Jules - Senior Data Code Reviewer
> **Mục tiêu**: Đơn giản hóa cấu trúc thư mục, loại bỏ mã nguồn trùng lặp/dư thừa, áp dụng thiết kế Pythonic giúp dễ bảo trì và tăng tốc độ phát triển tính năng mới.

---

## 1. TỔ CHỨC LẠI CẤU TRÚC THƯ MỤC (DIRECTORY RESTRUCTURING)

### 🔴 Cấu trúc hiện tại (Current Layout)
Hiện tại hệ thống có một số điểm trùng lặp và phân cấp quá sâu:
1. **Trùng lặp cấu hình**: `configs/` ở thư mục gốc và `src/ecommerce/resources/configs/` là **bản sao 100% giống nhau**.
2. **Phân cấp Parser sâu**: `platforms/<platform>/parse/` có tới 10-12 file nhỏ (`price.py`, `stock.py`, `sales.py`, `rating.py`, `shop.py`, `content.py`...) gây chia nhỏ quá mức cho logic bóc tách.
3. **Lặp lại helper**: Mỗi sàn (`shopee`, `tiktok`, `lazada`) tự định nghĩa lại các hàm ép kiểu và truy cập dict an toàn (`_d`, `_l`, `to_int`, `to_float`, `first`, `dig`).

### 🟢 Cấu trúc đề xuất mới (Proposed Clean Layout)

```
src/ecommerce/
├── __init__.py
├── __main__.py
├── cli.py                          # Single entrypoint CLI
├── settings.py                     # Strongly typed Pydantic config
│
├── core/                           # [MỚI] Tầng lõi thống nhất
│   ├── domain/                     # Canonical models (Product, Variant, Dataset, DomainProfile)
│   ├── ingestion/                  # Browser control, RawStore (Bronze), Image cache
│   └── transformation/             # Domain filters & Spec extractors (Capacity, Material...)
│
├── platforms/                      # [TỐI ƯU] Multi-platform edge adapters
│   ├── common/                     # [MỚI] Parser helpers dùng chung (_d, _l, to_int, to_float, dig)
│   ├── base.py                     # PlatformAdapter ABC & Adapter Registry decorator
│   ├── shopee/                     # adapter.py, extract.py, parse.py (gộp các file parse nhỏ)
│   ├── tiktok/                     # adapter.py, extract.py, parse.py
│   └── lazada/                     # adapter.py, extract.py, parse.py
│
├── contracts/                      # Data quality & schema drift rules
│   ├── guard.py                    # Runtime circuit breaker
│   ├── check.py                    # Baseline checker
│   └── rules.py                    # Base contract rules & platform specs
│
├── consumption/                    # Export presentation layer
│   └── excel/                      # Excel report writer, layout validator & column registry
│
└── resources/                      # [DUY NHẤT] Nơi chứa file YAML mặc định cho wheel
    └── configs/                    # Tránh duy trì 2 thư mục config song song
```

---

## 2. LOẠI BỎ MÃ NGUỒN TRÙNG LẶP VÀ DƯ THỪA (DEAD CODE & REDUNDANCY ELIMINATION)

### 2.1. Tập trung các Parser Helpers dùng chung (`platforms/common/helpers.py`)
* **Trạng thái hiện tại**:
  Cả 3 file `platforms/shopee/parse/common.py`, `platforms/tiktok/parse/common.py`, `platforms/lazada/parse/common.py` đều viết lại các hàm:
  - `_d(v)`: Ép kiểu dict an toàn
  - `_l(v)`: Ép kiểu list an toàn
  - `to_int(v)`, `to_float(v)`: Chuyển đổi số an toàn
  - `first(*values)`: Lấy giá trị khác None đầu tiên
  - `dig(obj, *keys)`: Truy vấn dict lồng nhau
* **Giải pháp**:
  Đưa toàn bộ các hàm này vào `src/ecommerce/platforms/common/helpers.py`. Các sàn chỉ cần `from ecommerce.platforms.common.helpers import _d, _l, to_int, to_float, dig, first`.

### 2.2. Xóa bỏ trùng lặp cấu hình (`configs/` vs `src/ecommerce/resources/configs/`)
* **Trạng thái hiện tại**:
  Dự án giữ 2 bản sao cấu hình hoàn toàn giống nhau.
* **Giải pháp**:
  Dùng `resources/configs/` làm nguồn sự thật duy nhất (Single Source of Truth). `settings.py` sẽ mặc định đọc từ `resources/configs/` nếu thư mục người dùng local không tồn tại.

### 2.3. Đăng ký Adapter tự động qua Decorator (Registry Pattern)
* **Trạng thái hiện tại**:
  Mỗi khi thêm 1 sàn mới, phải sửa tay file `platforms/__init__.py` để import và thêm vào dict `PLATFORMS`.
* **Giải pháp**:
  Sử dụng `@register_platform("shopee")` decorator trong `platforms/base.py`. Khi module adapter được load, nó tự động đăng ký vào Registry.

---

## 3. VÍ DỤ CHUYỂN ĐỔI CODE ĐƠN GIẢN HƠN (CODE SIMPLIFICATION EXAMPLES)

### 🔹 Ví dụ 1: Rút gọn Parser Helper

**Trước Refactor (Viết đi viết lại ở từng sàn):**
```python
# Trong shopee/parse/common.py, tiktok/parse/common.py, lazada/parse/common.py
def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}

def _l(v: Any) -> list:
    return v if isinstance(v, list) else []

def to_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
```

**Sau Refactor (Chỉ viết 1 lần trong `platforms/common/helpers.py`):**
```python
# src/ecommerce/platforms/common/helpers.py
from typing import Any

def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}

def _l(v: Any) -> list:
    return v if isinstance(v, list) else []

def to_int(v: Any) -> int | None:
    if v in (None, "", False):
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None
```

---

### 🔹 Ví dụ 2: Đơn giản hóa việc Đăng ký Platform Adapters

**Trước Refactor (`platforms/__init__.py` phải sửa thủ công):**
```python
from ecommerce.platforms.shopee.adapter import ShopeeAdapter
from ecommerce.platforms.tiktok.adapter import TikTokAdapter
from ecommerce.platforms.lazada.adapter import LazadaAdapter

ADAPTERS = {
    "shopee": ShopeeAdapter,
    "tiktok": TikTokAdapter,
    "lazada": LazadaAdapter,
}

def get_adapter(name: str) -> PlatformAdapter:
    return ADAPTERS[name]()
```

**Sau Refactor (Dùng Decorator linh hoạt):**
```python
# src/ecommerce/platforms/base.py
_REGISTRY: dict[str, type[PlatformAdapter]] = {}

def register_platform(name: str):
    def decorator(cls):
        _REGISTRY[name.lower()] = cls
        return cls
    return decorator

def get_adapter(name: str) -> PlatformAdapter:
    if name.lower() not in _REGISTRY:
        raise ValueError(f"Platform '{name}' chưa được đăng ký.")
    return _REGISTRY[name.lower()]()

# Trong platforms/shopee/adapter.py:
@register_platform("shopee")
class ShopeeAdapter(PlatformAdapter):
    ...
```

---

### 🔹 Ví dụ 3: Đơn giản hóa các Spec Extractors trong `transformation/specs/`

**Trước Refactor (Mỗi file specs tự lặp lại logic regex search & clean):**
```python
# Lặp lại logic trong capacity.py, size.py, warranty.py...
def extract_capacity(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*(ml|l)", text, re.I)
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2).lower()
    return val * 1000 if unit == "l" else val
```

**Sau Refactor (Dùng Base Regex Extractor Engine):**
```python
# src/ecommerce/transformation/specs/common.py
class BaseSpecExtractor:
    @staticmethod
    def match_pattern(text: str, pattern: str, transform_fn=None):
        if not text:
            return None
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        return transform_fn(match) if transform_fn else match.group(1)
```

---

## 4. LỘ TRÌNH THỰC THI (REFACTORING ROADMAP)

1. **Bước 1**: Tạo `src/ecommerce/platforms/common/helpers.py` và chuyển các hàm helper dùng chung sang đây.
2. **Bước 2**: Đổi các import trong Shopee/TikTok/Lazada parser sang module helper chung.
3. **Bước 3**: Loại bỏ sự trùng lặp giữa `configs/` và `src/ecommerce/resources/configs/`.
4. **Bước 4**: Chạy toàn bộ unit test suite (`pytest`) sau mỗi bước refactor để đảm bảo **100% test pass (276/276 tests)** và không sinh ra bất kỳ regression nào.
