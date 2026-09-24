"""本地受控测试夹具页面（仅用于回归测试与演示流程）。

这些页面是**虚构的**，只用于在完全不接触真实电商站点的前提下，
跑通与真实站点相同的浏览器代码路径。界面上必须标注「测试夹具」，
不得与真实平台结果混淆。

启动方式（测试用）：``FixtureServer.start()`` 返回基址，
例如 ``http://127.0.0.1:<port>/jd/search.html``。
"""
from __future__ import annotations

import http.server
import threading
from dataclasses import dataclass
from typing import Dict, Optional

_JD_SEARCH = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>搜索：{keyword} - 夹具</title>
<meta property="og:title" content="搜索结果">
</head><body>
<nav><a href="/jd/home.html">首页</a></nav>
<h1>搜索结果：{keyword}</h1>
<div class="item-list">{links}</div>
<div class="fixture-banner">本地测试夹具 · 虚构数据 · 不是真实平台报价</div>
</body></html>"""

_JD_HOME_LOGGED_OUT = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>夹具首页</title></head><body>
<h1>京东（夹具）</h1>
<div class="login-info"><a href="/login.html">请登录</a></div>
</body></html>"""

_JD_HOME_LOGGED_IN = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>夹具首页</title></head><body>
<h1>京东（夹具）</h1>
<div class="user-name">测试用户</div>
<nav><a href="/jd/search.html">搜索</a></nav>
</body></html>"""

_JD_PRODUCT = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title} - 夹具商品页</title>
<meta property="og:title" content="{title}">
<script type="application/ld+json">
{{"@type":"Product","name":"{title}","offers":{{"@type":"Offer","price":"{price}","priceCurrency":"CNY"}},
 "seller":{{"@type":"Organization","name":"{shop}"}}}}
</script>
</head><body>
<h1>{title}</h1>
<div class="fixture-banner">本地测试夹具 · 虚构数据 · 不是真实平台报价</div>
<div class="shop-name">{shop}</div>
<div class="price">¥{price}</div>
<div class="sku">颜色：{color}；尺码：{size}</div>
{coupons}
<div class="promotion">限时直降 50 元</div>
<div class="policy">7天无理由退货</div>
<div class="policy">全国联保，一年保修</div>
<div class="policy">满 99 元包邮</div>
<div class="policy">假一赔十</div>
<div class="sales">{sales}</div>
<div class="region">配送至：{region}</div>
</body></html>"""

_CAPTCHA = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>安全验证 - 夹具</title></head><body>
<h1>安全验证</h1><p>请完成滑块验证后继续访问。</p>
</body></html>"""

_LOGIN_EXPIRED = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>登录已过期 - 夹具</title></head><body>
<h1>登录已过期</h1><p>请登录后查看商品价格。</p>
</body></html>"""


@dataclass
class FixtureProduct:
    """夹具里的一个商品。规格写进页面，保证不同商品确实不同。"""

    id: str
    title: str
    price: str = "899.00"
    color: str = "黑色"
    size: str = "L"
    shop: str = "示例官方旗舰店"
    sales: str = "已售 1200 件"
    coupons: tuple = ("满 1000 减 100 元店铺券（已领取，可用）", "国补 15%（需本人资格核实）")


@dataclass
class FixtureSpec:
    keyword: str = "冲锋衣 男 防雨"
    products: tuple = (
        FixtureProduct(
            id="1001001",
            title="探路者 三合一冲锋衣 男 防雨透气 TAWJ91717 黑色 L",
            price="899.00",
            color="黑色",
            size="L",
            sales="已售 1200 件",
        ),
        FixtureProduct(
            id="1001002",
            title="探路者 三合一冲锋衣 男 防雨透气 TAWJ91717 黑色 XL",
            price="929.00",
            color="黑色",
            size="XL",
            shop="示例自营旗舰店",
            sales="已售 860 件",
        ),
        FixtureProduct(
            id="1002003",
            title="伯希和 轻量冲锋衣 女 防晒 UPF50+ PELLIOT8823 白色 M",
            price="459.00",
            color="白色",
            size="M",
            shop="另一示例旗舰店",
            sales="已售 3400 件",
            coupons=("满 400 减 30 元店铺券（去领取）",),
        ),
    )
    region: str = "北京市"
    # 首页是否呈现已登录状态（用于测试"需要用户登录"分支）
    home_logged_in: bool = True

    def product(self, product_id: Optional[str]) -> FixtureProduct:
        for item in self.products:
            if item.id == product_id:
                return item
        return self.products[0]


class _Handler(http.server.BaseHTTPRequestHandler):
    spec: FixtureSpec = FixtureSpec()

    def log_message(self, *args):  # 静音
        pass

    def _send(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        spec = self.spec
        if path == "/jd/home.html":
            if spec.home_logged_in:
                return self._send(_JD_HOME_LOGGED_IN)
            return self._send(_JD_HOME_LOGGED_OUT)
        if path == "/jd/search.html":
            keyword = (query.get("keyword") or [spec.keyword])[0]
            links = "".join(
                f'<a class="item" href="/jd/product.html?id={item.id}&title={item.title}">'
                f'<span class="title">{item.title}</span></a>'
                for item in spec.products
            )
            return self._send(
                _JD_SEARCH.format(keyword=keyword, links=links)
            )
        if path == "/jd/product.html":
            item = spec.product((query.get("id") or [None])[0])
            coupons = "".join(f'<div class="coupon">{text}</div>' for text in item.coupons)
            return self._send(
                _JD_PRODUCT.format(
                    title=item.title,
                    price=item.price,
                    shop=item.shop,
                    color=item.color,
                    size=item.size,
                    sales=item.sales,
                    coupons=coupons,
                    region=spec.region,
                )
            )
        if path == "/captcha.html":
            return self._send(_CAPTCHA)
        if path == "/login-expired.html":
            return self._send(_LOGIN_EXPIRED)
        return self._send("<html><body><h1>404 夹具</h1></body></html>", 404)


class FixtureServer:
    """在 127.0.0.1 的随机端口上提供夹具页面。"""

    def __init__(self, spec: Optional[FixtureSpec] = None):
        self.spec = spec or FixtureSpec()
        handler = type("BoundHandler", (_Handler,), {"spec": self.spec})
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> "FixtureServer":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "FixtureServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def fixture_urls(spec: Optional[FixtureSpec] = None) -> Dict[str, str]:
    """不需要起服务时，用 data: URL 之外的静态说明（仅文档用途）。"""
    return {
        "search": "/jd/search.html",
        "product": "/jd/product.html",
        "captcha": "/captcha.html",
        "login_expired": "/login-expired.html",
    }
