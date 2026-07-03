"""
JD (京东) Product Adapter
Docs: https://open.jd.com/home/home#/doc/api?apiCateId=102

Production: Replace mock data with real JD Open API calls.
Key APIs:
  - jd.union.open.goods.query     (search products)
  - jd.union.open.goods.promotiongoodsinfo.query (price & discount)
  - jd.union.open.category.goods.get (category browse)
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


class JDAdapter:
    """
    Adapter for JD Open Platform.
    Switch USE_MOCK = False once you have real credentials.
    """
    USE_MOCK = True
    BASE_URL = settings.JD_API_BASE_URL
    APP_KEY = settings.JD_APP_KEY
    APP_SECRET = settings.JD_APP_SECRET
    ACCESS_TOKEN = settings.JD_ACCESS_TOKEN

    def _sign(self, params: Dict[str, str]) -> str:
        """Generate JD API signature (MD5 method)"""
        sorted_params = sorted(params.items())
        sign_str = self.APP_SECRET
        for k, v in sorted_params:
            sign_str += k + str(v)
        sign_str += self.APP_SECRET
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    def _build_params(self, method: str, biz_param: Dict) -> Dict:
        params = {
            "app_key": self.APP_KEY,
            "method": method,
            "access_token": self.ACCESS_TOKEN,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
            "360buy_param_json": json.dumps(biz_param),
        }
        params["sign"] = self._sign(params)
        return params

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def search_products(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by: str = "default",
    ) -> List[Product]:
        if self.USE_MOCK:
            return self._mock_search(keyword, page_size)

        biz_param = {
            "keyword": keyword,
            "pageIndex": page,
            "pageSize": page_size,
            "sortName": sort_by,
        }
        if min_price:
            biz_param["pricefrom"] = min_price
        if max_price:
            biz_param["priceto"] = max_price

        params = self._build_params("jd.union.open.goods.query", biz_param)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.BASE_URL, data=params)
            resp.raise_for_status()
            data = resp.json()
        return self._parse_search_response(data)

    def _parse_search_response(self, data: Dict) -> List[Product]:
        products = []
        items = data.get("jd_union_open_goods_query_response", {}).get("result", {}).get("data", [])
        for item in items:
            sku_name = item.get("skuName", "")
            sku_id = str(item.get("skuId", ""))
            price_info = item.get("priceInfo", {})
            price = float(price_info.get("price", 0))
            original_price = float(price_info.get("originalPrice", price))
            url = f"https://item.jd.com/{sku_id}.html"
            product = Product(
                platform=Platform.JD,
                product_id=sku_id,
                title=sku_name,
                price=price,
                original_price=original_price,
                discount_rate=round((1 - price / original_price) * 100, 1) if original_price > 0 else None,
                brand=item.get("brandName"),
                category=item.get("cid3Name"),
                url=url,
                images=[item.get("imageInfo", {}).get("imageUrl", "")],
                sales=str(item.get("inOrderCount30Days", 0)) + "人付款",
                delivery="京东自营",
                fetched_at=datetime.now(),
                tags=["京东自营"],
            )
            products.append(product)
        return products

    def _mock_search(self, keyword: str, count: int = 5) -> List[Product]:
        logger.info(f"[JD Mock] Searching: {keyword}")
        results = []
        mock_items = [
            {"id": "100050557484", "title": f"{keyword} - 京东自营 旗舰店", "price": 4999.0, "original": 5299.0, "sales": "12580人付款", "rating": 4.9},
            {"id": "100038993800", "title": f"{keyword} 高性能版 京东把控", "price": 5499.0, "original": 5799.0, "sales": "8920人付款", "rating": 4.8},
            {"id": "100072648801", "title": f"{keyword} Pro 版 官方旗舰店", "price": 6299.0, "original": 6699.0, "sales": "5430人付款", "rating": 4.7},
            {"id": "100045883912", "title": f"{keyword} 入门推荐款 京东优选", "price": 3299.0, "original": 3599.0, "sales": "22100人付款", "rating": 4.8},
            {"id": "100061239045", "title": f"{keyword} 标准版 京东自营", "price": 2999.0, "original": 3199.0, "sales": "31500人付款", "rating": 4.6},
        ]
        for i, item in enumerate(mock_items[:count]):
            results.append(Product(
                platform=Platform.JD,
                product_id=item["id"],
                title=item["title"],
                price=item["price"],
                original_price=item["original"],
                discount_rate=round((1 - item["price"] / item["original"]) * 100, 1),
                store_name="京东自营",
                brand=keyword.split()[0] if keyword else "Unknown",
                category="数码产品",
                url=f"https://item.jd.com/{item['id']}.html",
                images=[f"https://img14.360buyimg.com/n1/{item['id']}.jpg"],
                sales=item["sales"],
                rating=item["rating"],
                review_count=int(item["sales"].replace("人付款", "").replace(",", "")),
                delivery="京东快递 次日1个工作日内送达",
                fetched_at=datetime.now(),
                tags=["京东自营", "正品保障", "次日达"],
            ))
        return results

    async def get_product_detail(self, product_id: str) -> Optional[Product]:
        if self.USE_MOCK:
            mock = self._mock_search("product", 1)
            if mock:
                mock[0].product_id = product_id
                return mock[0]
            return None
        # TODO: implement real detail API
        return None


jd_adapter = JDAdapter()
