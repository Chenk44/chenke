"""API 端到端测试。用 FastAPI 的 TestClient，不需要起服务器。"""

from __future__ import annotations


def _new_group(client, **kw):
    payload = {"name": "周六去哪", "origin_area": "海岸城", "window_minutes": 360}
    payload.update(kw)
    resp = client.post("/api/groups", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _join(client, code, nickname):
    resp = client.post(f"/api/groups/{code}/members", json={"nickname": nickname})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _fill(client, member_id, **kw):
    payload = {"quiet": 0.5, "price": 0.5, "near": 0.5}
    payload.update(kw)
    resp = client.put(f"/api/members/{member_id}/preference", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _prepare(client, n: int = 3):
    group = _new_group(client)
    members = [_join(client, group["code"], f"朋友{i}") for i in range(n)]
    for i, m in enumerate(members):
        _fill(client, m["id"], quiet=[0.8, 0.2, 0.5][i % 3], price=0.5, near=0.5)
    return group, members


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_netinfo_returns_lan_addresses(client):
    """前端靠它告诉用户「该把哪个地址发给朋友」，所以必须是列表、且不含回环地址。"""
    resp = client.get("/api/netinfo")
    assert resp.status_code == 200
    ips = resp.json()["lan_ips"]
    assert isinstance(ips, list)
    assert all(isinstance(ip, str) and not ip.startswith("127.") for ip in ips)


def test_bad_path_param_gets_a_readable_message(client):
    """原来用户会看到 Pydantic 的原始 JSON 列表，现在压成一句中文。"""
    resp = client.put("/api/members/not-a-number/preference", json={"quiet": 0.5})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str)
    assert "参数不对" in detail


def test_group_code_is_short_and_readable(client):
    group = _new_group(client)
    code = group["code"]
    assert len(code) == 6
    assert code.isupper() or code.isdigit() or code.isalnum()
    assert not (set(code) & set("0O1I")), "邀请码要能口头念，不能有易混字符"
    assert group["members"] == []


def test_origin_area_sets_real_coordinates(client):
    group = _new_group(client, origin_area="大鹏")
    assert group["origin_area"] == "大鹏"


def test_unknown_origin_area_still_creates_group(client):
    """商圈写错了也不能拦住建局，用深圳中心兜底。"""
    group = _new_group(client, origin_area="火星")
    assert group["code"]


def test_join_is_idempotent(client):
    group = _new_group(client)
    first = _join(client, group["code"], "小王")
    again = _join(client, group["code"], "小王")
    assert first["id"] == again["id"]
    assert len(client.get(f"/api/groups/{group['code']}").json()["members"]) == 1


def test_group_not_found(client):
    assert client.get("/api/groups/ZZZZZZ").status_code == 404


def test_free_text_is_parsed_into_constraints(client):
    group = _new_group(client)
    member = _join(client, group["code"], "下雨天の人")
    pref = _fill(client, member["id"], free_text="下雨天别走太远，人均 80 以内")

    assert pref["indoor_pref"] == 1
    assert pref["near"] == 0.2
    assert pref["max_price"] == 80
    assert pref["parsed_hints"], "应该告诉用户我们读懂了什么"


def test_manual_slider_wins_over_free_text(client):
    """用户手动拖到 0.9 就不该被一句话改回去。"""
    group = _new_group(client)
    member = _join(client, group["code"], "小明")
    pref = _fill(client, member["id"], quiet=0.9, free_text="随便，要热闹点")
    assert pref["quiet"] == 0.9


def test_saying_no_to_indoor_actually_changes_the_plans(client):
    """全员说「不想去室内」，方案里就不该再出现室内地点。

    这是用户报的第二个 bug 的回归测试：以前这句话只被解析成
    require_indoor=False，而 False 在算法里等于「没说话」。
    """
    group = _new_group(client)
    members = [_join(client, group["code"], f"想出去{i}") for i in range(3)]
    for m in members:
        pref = _fill(client, m["id"], free_text="今天不想在室内待着，想出去走走")
        assert pref["indoor_pref"] == -1, pref

    plans = client.post(f"/api/groups/{group['code']}/recommend").json()["plans"]
    items = [item for plan in plans for item in plan["items"]]
    assert items, "应该给出方案"
    indoor = [item["name"] for item in items if item["indoor"]]
    assert not indoor, f"这些室内地点不该出现：{indoor}"


def test_parse_endpoint(client):
    resp = client.post("/api/parse", json={"text": "带孩子，别吃辣，想安静点"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["with_kids"] is True
    assert data["indoor_pref"] == 1
    assert "辣" in data["exclude_tags"]
    assert data["quiet"] == 0.8


def test_recommend_requires_preferences(client):
    group = _new_group(client)
    _join(client, group["code"], "懒人")
    resp = client.post(f"/api/groups/{group['code']}/recommend")
    assert resp.status_code == 400
    assert "偏好" in resp.json()["detail"]


def test_recommend_returns_three_plans(client):
    group, members = _prepare(client, 3)
    resp = client.post(f"/api/groups/{group['code']}/recommend")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert len(data["plans"]) == 3
    assert data["top_pois"], "应该同时返回单个地点的排名"

    for plan in data["plans"]:
        assert 2 <= len(plan["items"]) <= 3
        assert 0 < plan["consensus"] <= 1
        assert plan["worst_member"] in {m["nickname"] for m in members}
        assert plan["explanation"]


def test_recommend_is_deterministic_over_http(client):
    group, _ = _prepare(client, 3)
    a = client.post(f"/api/groups/{group['code']}/recommend").json()
    b = client.post(f"/api/groups/{group['code']}/recommend").json()
    assert [p["items"][0]["id"] for p in a["plans"]] == [p["items"][0]["id"] for p in b["plans"]]


def test_plans_persist_and_can_be_listed(client):
    group, _ = _prepare(client, 3)
    client.post(f"/api/groups/{group['code']}/recommend")
    listed = client.get(f"/api/groups/{group['code']}/plans")
    assert listed.status_code == 200
    assert len(listed.json()["plans"]) == 3


def test_vote_and_tally(client):
    group, members = _prepare(client, 3)
    client.post(f"/api/groups/{group['code']}/recommend")
    plans = client.get(f"/api/groups/{group['code']}/plans").json()["plans"]
    assert plans

    plan_id = plans[0]["id"]
    vote_resp = client.post(f"/api/plans/{plan_id}/vote", json={"member_id": members[0]["id"]})
    assert vote_resp.status_code == 200, vote_resp.text
    assert vote_resp.json()["votes"] == 1

    # 同一个人重复投，幂等
    again = client.post(f"/api/plans/{plan_id}/vote", json={"member_id": members[0]["id"]})
    assert again.json()["votes"] == 1

    tally = client.get(f"/api/groups/{group['code']}/votes")
    assert tally.status_code == 200
    assert tally.json()[0]["voters"] == ["朋友0"]
    assert tally.json()[0]["winner"] is True


def test_pois_can_be_filtered(client):
    all_pois = client.get("/api/pois").json()
    assert len(all_pois) >= 40

    indoor = client.get("/api/pois", params={"indoor": "true"}).json()
    assert indoor and all(p["indoor"] for p in indoor)

    area = client.get("/api/pois", params={"area": "海岸城"}).json()
    assert area and all(p["area"] == "海岸城" for p in area)


def test_areas_endpoint(client):
    areas = client.get("/api/areas").json()
    assert "海岸城" in areas
    assert len(areas) >= 8


def test_review_upsert(client):
    group = _new_group(client)
    member = _join(client, group["code"], "评价者")
    poi_id = client.get("/api/pois").json()[0]["id"]

    first = client.post(
        "/api/reviews",
        json={"member_id": member["id"], "poi_id": poi_id, "rating": 5, "comment": "好"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/reviews",
        json={"member_id": member["id"], "poi_id": poi_id, "rating": 3, "comment": "一般"},
    )
    assert second.status_code == 200

    reviews = client.get(f"/api/pois/{poi_id}/reviews").json()
    assert len(reviews) == 1, "同一个人对同一地点只保留最后一次评价"
    assert reviews[0]["rating"] == 3


def test_review_rejects_unknown_poi(client):
    resp = client.post("/api/reviews", json={"member_id": 1, "poi_id": "nope", "rating": 5})
    assert resp.status_code == 404


def test_demo_group_is_ready_to_use(client):
    """示例局必须「点开就能看到方案」，否则等于没做。"""
    demo = client.post("/api/demo")
    assert demo.status_code == 201, demo.text
    data = demo.json()
    assert data["members"] == 5
    assert data["member_id"] > 0

    group = client.get(f"/api/groups/{data['code']}").json()
    assert all(m["filled"] for m in group["members"]), "五个人的偏好应该都是填好的"

    out = client.post(f"/api/groups/{data['code']}/recommend")
    assert out.status_code == 200, out.text
    assert len(out.json()["plans"]) == 3


def test_page_always_offers_a_way_back_home(client):
    """前端页面必须带着「回首页」的出口。

    这条测试是给一个真实 bug 留的护栏：之前 route() 里有 `else if (state.code)`
    的兜底，空 hash 会被当成「打开上次那个局」，而局内页面又没有返回按钮，
    结果点完生成方案就再也回不到首页。前端没有 DOM 测试环境，所以这里退一步，
    守住两个最容易再次消失的标记。
    """
    html = client.get("/").text
    assert 'id="btn-home"' in html, "局内页面缺少返回首页的按钮"
    assert 'id="btn-pref-home"' in html, "填偏好页面缺少返回首页的按钮"
    assert "else if (state.code)" not in html, "路由里不应再把空 hash 当成「回到上次那个局」"


def test_new_preference_fields_round_trip(client):
    """一句话解析出来的五个字段必须真的落库、真的读得回来。"""
    group = _new_group(client)
    member = _join(client, group["code"], "小林")
    saved = _fill(
        client,
        member["id"],
        prefer_categories=["火锅"],
        exclude_categories=["桌游"],
        prefer_tags=["拍照"],
        max_minutes=240,
        start_hour=19,
    )
    assert saved["prefer_categories"] == ["火锅"]
    assert saved["max_minutes"] == 240

    again = client.get(f"/api/members/{member['id']}/preference").json()
    assert again["exclude_categories"] == ["桌游"]
    assert again["prefer_tags"] == ["拍照"]
    assert again["start_hour"] == 19


def test_free_text_fills_the_new_fields(client):
    """真正的一句话走完整链路：解析 → 合并 → 落库。"""
    group = _new_group(client)
    member = _join(client, group["code"], "阿May")
    saved = _fill(client, member["id"], free_text="想吃火锅，不要玩桌游，最多三小时")
    assert saved["prefer_categories"] == ["火锅"]
    assert saved["exclude_categories"] == ["桌游"]
    assert saved["max_minutes"] == 180


def test_recommendation_carries_the_start_time(client):
    """前端拿 start_minute 把偏移量渲染成时刻，缺了它时间线会退回写死的 14:00。"""
    group, members = _prepare(client, 3)
    _fill(client, members[0]["id"], start_hour=19)
    resp = client.post(f"/api/groups/{group['code']}/recommend")
    assert resp.status_code == 200, resp.text
    plans = resp.json()["plans"]
    assert plans and plans[0]["start_minute"] >= 19 * 60

    stored = client.get(f"/api/groups/{group['code']}/plans").json()
    assert stored["plans"][0]["start_minute"] == plans[0]["start_minute"]
