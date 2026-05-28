#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборщик отзывов JOO School из 2ГИС -> data.json для дашборда.

Что делает:
  1. Для каждого филиала дергает публичный API отзывов 2ГИС.
  2. Берёт рейтинг, число отзывов и сами отзывы (текст, оценка, дата).
  3. Считает сентимент (по оценке) и темы (по ключевым словам, рус+каз).
  4. Пишет data.json рядом с дашбордом.

Запуск:
    pip install requests
    python collect.py

Дашборд (joo-dashboard.html) при открытии сам подхватит свежий data.json.
Чтобы это работало в браузере, дашборд и data.json нужно открывать с веб-сервера
(GitHub Pages / Netlify / `python -m http.server`), а не двойным кликом из папки.
"""

import json, time, datetime, sys
import requests

# Публичный ключ API отзывов 2ГИС (из открытых страниц 2ГИС).
API_KEY = "6e7e1929-4ea9-4a5d-8c05-d601860389bd"
REVIEWS_PER_BRANCH = 600   # тянуть все отзывы (по 50 на страницу)

# Базовые рейтинг и число отзывов (на случай, если API не вернёт их в мете).
R_DEF   = {"mega":4.7,"auezov":4.6,"alatau":4.4,"medeu":4.0,"shym":4.6,"aktau":4.8,"aktobe":4.6,"atyrau":4.5}
REV_DEF = {"mega":144,"auezov":117,"alatau":223,"medeu":108,"shym":232,"aktau":81,"aktobe":76,"atyrau":45}

# Филиалы сети JOO. branch_id и city — для API; остальное — для отображения.
BRANCHES = [
    {"id":"mega",   "branch_id":"70000001057657673","city_slug":"almaty",  "nm":"JOO Mega",    "city":"Алматы", "dist":"Бостандыкский р-н","addr":"пер. Дружбы, 14Б",     "votes":522},
    {"id":"auezov", "branch_id":"70000001100353443","city_slug":"almaty",  "nm":"JOO Auezov",  "city":"Алматы", "dist":"Ауэзовский р-н",   "addr":"ул. Цветочная, 1/14",  "votes":407},
    {"id":"alatau", "branch_id":"70000001077051866","city_slug":"almaty",  "nm":"JOO Alatau",  "city":"Алматы", "dist":"Алатауский р-н",   "addr":"ул. Байтерекова, 3",   "votes":670},
    {"id":"medeu",  "branch_id":"70000001100353290","city_slug":"almaty",  "nm":"JOO Medeu",   "city":"Алматы", "dist":"Медеуский р-н",    "addr":"ул. Халиуллина, 210а", "votes":385},
    {"id":"shym",   "branch_id":"70000001062369271","city_slug":"shymkent","nm":"JOO Shymkent","city":"Шымкент","dist":"Туран р-н",        "addr":"пр. Байдибек би, 14/1","votes":982},
    {"id":"aktau",  "branch_id":"70000001062488569","city_slug":"aktau",   "nm":"JOO Aktau",   "city":"Актау",  "dist":"31А мкр",          "addr":"мкр 31А, 1/3",         "votes":463},
    {"id":"aktobe", "branch_id":"70000001100414005","city_slug":"aktobe",  "nm":"JOO Aktobe",  "city":"Актобе", "dist":"Алтын Орда",       "addr":"мкр Алтын Орда, 3",    "votes":272},
    {"id":"atyrau", "branch_id":"70000001078622820","city_slug":"atyrau",  "nm":"JOO Atyrau",  "city":"Атырау", "dist":"Ак Шагала",        "addr":"ул. Н. Тлендиева, 38а","votes":203},
]

# ---- словари для классификации (рус + каз, нижний регистр) ----
NEG_WORDS = ["плох","ужас","отврат","груб","хамств","не рекоменд","обман","не стоит","впуст","развод",
             "слаб","нет воды","нет туалет","буллинг","унижа","текучк","ушли","забрал","уволил","сменил",
             "дорог","завыш","не готов","некомпетент","жаман","нашар","өтірік","қымбат","болмайды","жоқ"]
POS_WORDS = ["отлич","спасиб","лучш","рекоменд","нрав","любл","профессионал","классн","супер","доволь",
             "благодар","топ","кайф","керемет","жақсы","рахмет","рақмет","ұнайды","мықты","күшті","тамаша"]

THEME_KW = {
    "Преподаватели": ["учител","препод","куратор","педагог","мугал","мұғал","апай","ағай","agai","репетитор"],
    "Программа":     ["програм","методик","урок","предмет","science","англ","матем","ielts","ент","ұбт","нیш","ниш","бил"],
    "Результаты":    ["грант","поступ","балл","результат","түст","вуз","универ","олимпиад"],
    "Атмосфера":     ["атмосфер","отношен","забот","друж","комфорт","безопас","орта","семь","family"],
    "Инфраструктура":["здани","ремонт","туалет","кабинет","чист","грязн","холодн","жарко","вода","свет","столов","еда","буфет","мебел","кондиционер"],
    "Администрация": ["директ","завуч","админ","руковод","расписан","ответ","комму","басшы"],
    "Цена":          ["цена","оплат","дорог","деньг","стоим","ақша","қымбат","төле"],
    "Дисциплина":    ["форм","телефон","строг","дисциплин","правил","режим"],
}

def classify_theme(text):
    t = text.lower()
    for theme, kws in THEME_KW.items():
        if any(k in t for k in kws):
            return theme
    return "Прочее"

def sentiment(rating, text):
    if rating:
        if rating >= 4: return "pos"
        if rating == 3: return "neu"
        return "neg"
    t = text.lower()
    p = sum(w in t for w in POS_WORDS); n = sum(w in t for w in NEG_WORDS)
    return "pos" if p > n else ("neg" if n > p else "neu")

def fetch_reviews(branch):
    """Тянем отзывы филиала постранично через offset_date."""
    url = f"https://public-api.reviews.2gis.com/3.0/branches/{branch['branch_id']}/reviews"
    headers = {"User-Agent":"Mozilla/5.0", "Referer":"https://2gis.kz/"}
    params = {
        "limit": 50,
        "rated": "true", "sort_by": "date_created",
        "key": API_KEY, "locale": "ru_KZ",
    }
    out, meta, offset = [], {}, None
    while len(out) < REVIEWS_PER_BRANCH:
        if offset: params["offset_date"] = offset
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            print(f"  ! {branch['nm']}: HTTP {r.status_code}", file=sys.stderr); break
        data = r.json()
        meta = data.get("meta", meta)
        items = data.get("reviews", []) or data.get("data", [])
        if not items: break
        for it in items:
            oa = it.get("official_answer") or it.get("official_answers") or it.get("comments")
            if isinstance(oa, list):
                answered = any((isinstance(x, dict) and x.get("text")) for x in oa)
            elif isinstance(oa, dict):
                answered = bool(oa.get("text"))
            else:
                answered = bool(oa)
            out.append({
                "rating": it.get("rating"),
                "text": (it.get("text") or "").strip(),
                "date": (it.get("date_created") or "")[:10],
                "answered": answered,
            })
        offset = items[-1].get("date_created")
        if not offset: break
        time.sleep(0.5)
    return out[:REVIEWS_PER_BRANCH], meta

def build():
    branches_out, revs_out = [], []
    for b in BRANCHES:
        print(f"… собираю {b['nm']}")
        try:
            reviews, meta = fetch_reviews(b)
        except Exception as e:
            print(f"  ! ошибка {b['nm']}: {e}", file=sys.stderr); reviews, meta = [], {}

        rating = round(float(meta.get("branch_rating") or 0), 1) or R_DEF.get(b["id"], 0)
        rev_count = meta.get("branch_reviews_count") or meta.get("total_count") or REV_DEF.get(b["id"]) or len(reviews)

        # сентимент по филиалу
        cnt = {"pos":0,"neu":0,"neg":0}
        praise, prob, monthly = {}, {}, {}
        for rv in reviews:
            s = sentiment(rv["rating"], rv["text"])
            cnt[s] += 1
            ym = (rv.get("date") or "")[:7]
            if ym: monthly[ym] = monthly.get(ym, 0) + 1
            if rv["text"] and len(rv["text"]) > 3:
                th = classify_theme(rv["text"])
                if th == "Прочее": continue
                if s == "pos": praise[th] = praise.get(th,0)+1
                elif s == "neg": prob[th] = prob.get(th,0)+1
                # 6 самых ярких текстовых отзывов на филиал в общий список
                if (s in ("pos","neg")) and len([x for x in revs_out if x["b"]==b["id"]]) < 8:
                    revs_out.append({"b":b["id"],"s":s,"th":th,
                                     "t":(rv["text"][:240]+"…") if len(rv["text"])>240 else rv["text"]})
        tot = max(1, sum(cnt.values()))
        sent = {k: round(v/tot*100) for k,v in cnt.items()}
        ans_n = sum(1 for rv in reviews if rv.get("answered"))
        answered_pct = round(ans_n/max(1,len(reviews))*100)  # реальный % по собранным отзывам

        praise_list = sorted(([k,v] for k,v in praise.items()), key=lambda x:-x[1])[:5]
        prob_list = [[k,v,"neg"] for k,v in sorted(prob.items(), key=lambda x:-x[1])[:6]]

        branches_out.append({
            "id":b["id"], "nm":b["nm"], "city":b["city"], "dist":b["dist"], "addr":b["addr"],
            "r": rating, "votes": b["votes"], "rev": rev_count,
            "answered": answered_pct,
            "sent": sent if reviews else {"pos":0,"neu":0,"neg":0},
            "monthly": monthly,
            "praise": praise_list or [["Нет данных",1]],
            "prob": prob_list or [["Нет данных",1,"neu"]],
        })

    total_rev = sum(b["rev"] for b in branches_out)
    if total_rev == 0:
        print("\n! Отзывы не получены (2ГИС, вероятно, заблокировал запросы с этого сервера).")
        print("  data.json НЕ перезаписан, чтобы не потерять прежние данные.")
        print("  Запустите сбор с компьютера в Казахстане — там 2ГИС доступен.")
        sys.exit(0)

    data = {
        "collected_at": datetime.date.today().isoformat(),
        "branches": branches_out,
        "revs": revs_out,
        # сетевые агрегаты дашборд пересчитает сам из branches; темы-облака пока статичные
    }
    with open("data.json","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\n✓ Готово: data.json ({len(branches_out)} филиалов, {len(revs_out)} отзывов)")

if __name__ == "__main__":
    build()
