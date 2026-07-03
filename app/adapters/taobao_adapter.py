"""
Taobao / Tmall Product Adapter
Docs: https://open.taobao.com/

Key APIs:
  - taobao.tbk.dg.item.get       (search affiliate products)
  - taobao.tbk.item.info.get     (product detail)
  - taobao.tbk.dg.optimus.material (smart recommend)

Production: Replace USE_MOCK = False and provide real APP_KEY + ACCESS_TOKEN.
"""
import hashlib
import time
import json
import httpx
from typing import List, Optional, Dict, Any
from datetime import datetime
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas import Product, Platform


class TaobaoAdapter:
    USE_MOCK = True
    BASE_URL = settings.TAOBAO_API_BASE_URL
    APP_KEY = settings.TAOBAO_APP_KEY
    APP_SECRET = settings.TAOBAO_APP_SECRET
    ACCESS_TOKEN = settings.TAOBAO_ACCESS_TOKEN

    def _sign(self, params: Dict[str, str]) -> str:
        """Taobao signature: sort params, wrap with secret, MD5"""
        sorted_params = sorted(params.items())
        sign_str = self.APP_SECRET
        for k, v in sorted_params:
            sign_str += k + str(v)
        sign_str += self.APP_SECRET
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    def _build_common_params(self, method: str) -> Dict:
        return {
            "method": method,
            "app_key": self.APP_KEY,
            "session": self.ACCESS_TOKEN,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def search_products(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by: str = "default",
        platform: Platform = Platform.TAOBAO,
    ) -> List[Product]:
        if self.USE_MOCK:
            return self._mock_search(keyword, page_size, platform)

        params = self._build_common_params("taobao.tbk.dg.item.get")
        params.update({
            "q": keyword,
            "page_no": page,
            "page_size": page_size,
            "sort": sort_by,
            "material_id": "2836",  # general goods
        })
        if min_price:
            params["start_price"] = int(min_price)
        if max_price:
            params["end_price"] = int(max_price)
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.BASE_URL, data=params)
            resp.raise_for_status()
            data = resp.json()
        return self._parse_response(data, platform)

    def _parse_response(self, data: Dict, platform: Platform) -> List[Product]:
        products = []
        result = data.get("tbk_dg_item_get_response", {}).get("result", {}).get("result_list", {}).get("map_data", [])
        for item in result:
            item_id = str(item.get("item_id", ""))
            title = item.get("title", "")
            zk_price = float(item.get("zk_final_price", 0))
            reserve_price = float(item.get("reserve_price", zk_price))
            url = item.get("item_url", f"https://item.taobao.com/item.htm?id={item_id}")
            products.append(Product(
                platform=platform,
                product_id=item_id,
                title=title,
                price=zk_price,
                original_price=reserve_price,
                store_name=item.get("nick"),
                url=url,
                images=[item.get("pict_url", "")],
                sales=str(item.get("volume", 0)) + "月售",
                delivery="包邮",
                fetched_at=datetime.now(),
                tags=[平台.value.upper()],
            ))
        return products

    def _mock_search(self, keyword: str, count: int = 5, platform: Platform = Platform.TAOBAO) -> List[Product]:
        logger.info(f"[{platform.value.upper()} Mock] Searching: {keyword}")
        prefix = "天猫" if platform == Platform.TMALL else "淘宝"
        mock_items = [
            {"id": "631234567890", "title": f"{keyword} {prefix}官方旗舰店 正品保障", "price": 4799.0, "original": 5199.0, "sales": "月售 9834", "rating": 4.8, "store": f"{keyword}官方旗舰店"},
            {"id": "631234567891", "title": f"{keyword} 品牌旗舰店 全国联保", "price": 5099.0, "original": 5599.0, "sales": "月售 7210", "rating": 4.7, "store": "品牌旗舰店"},
            {"id": "631234567892", "title": f"{keyword} 全网最低价 限时秒杀", "price": 4499.0, "original": 5099.0, "sales": "月售 15230", "rating": 4.6, "store": "数码超市"},
            {"id": "631234567893", "title": f"{keyword} Pro 内存升级版 夸克力赠老婆", "price": 5599.0, "original": 5999.0, "sales": "月售 4430", "rating": 4.9, "store": "天猫小店"},
            {"id": "631234567894", "title": f"{keyword} 学生底盘 免息分期款", "price": 3399.0, "original": 3799.0, "sales": "月售 28910", "rating": 4.5, "store": "小白数码旗舰店"},
        ]
        results = []
        for item in mock_items[:count]:
            results.append(Product(
                platform=platform,
                product_id=item["id"],
                title=item["title"],
                price=item["price"],
                original_price=item["original"],
                discount_rate=round((1 - item["price"] / item["original"]) * 100, 1),
                store_name=item["store"],
                category="数码产品",
                url=f"https://item.taobao.com/item.htm?id={item['id']}",
                images=[f"https://img.alicdn.com/imgextra/i1/{item['id']}.jpg"],
                sales=item["sales"],
                rating=item["rating"],
                delivery="包邮 全家全达",
                fetched_at=datetime.now(),
                tags=[prefix, "正品保障"],
            ))
        return results


class TmallAdapter(TaobaoAdapter):
    """Tmall shares the same API, just different platform tag"""
    async def search_products(self, keyword: str, page: int = 1, page_size: int = 20,
                              min_price: Optional[float] = None, max_price: Optional[float] = None,
                              sort_by: str = "default") -> List[Product]:
        return await super().search_products(keyword, page, page_size, min_price, max_price, sort_by, Platform.TMALL)


taobao_adapter = TaobaoAdapter()
tmall_adapter = TmallAdapter()
