import math
import os
from typing import List, Dict, Any, Optional
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

def _norm_num(x, low, high):
    try:
        x = float(x or 0)
        return (x - low) / (high - low) if high > low else 0.0
    except Exception:
        return 0.0

def _cat_one_hot(val: str, space: List[str]) -> List[float]:
    v = (val or "").strip().lower()
    return [1.0 if v == s else 0.0 for s in space]

def listing_feature_vector(lst) -> List[float]:
    price = _norm_num(getattr(lst, "price", 0), 0, 1_00_00_000)
    mileage = _norm_num(getattr(lst, "mileage", 0), 0, 3_00_000)
    year = _norm_num(getattr(lst.car, "year", 0), 1990, 2030)
    make_space = ["maruti suzuki","hyundai","kia","toyota","tata","mahindra","honda","skoda","volkswagen","renault","nissan","mg","bmw","audi","mercedes-benz"]
    body_space = ["hatchback","sedan","suv","mpv","coupe","pickup"]
    fuel_space = ["petrol","diesel","cng","hybrid","electric"]
    make = _cat_one_hot(getattr(lst.car, "make", None), make_space)
    body = _cat_one_hot(getattr(lst.car, "body_type", None), body_space)
    fuel = _cat_one_hot(getattr(lst.car, "fuel_type", None), fuel_space)
    return [price, mileage, year] + make + body + fuel

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    return (dot / (na*nb)) if na and nb else 0.0

def recommend_similar_listings(current, candidates, top_k=6) -> List[Any]:
    key = f"recs:{getattr(current, 'listing_id', None)}:{int(top_k or 6)}"
    cached = cache.get(key)
    if cached:
        return cached
    v0 = listing_feature_vector(current)
    scored = []
    for c in candidates:
        try:
            if getattr(c, "listing_id", None) == getattr(current, "listing_id", None):
                continue
            v = listing_feature_vector(c)
            s = _cosine(v0, v)
            scored.append((s, c))
        except Exception:
            continue
    scored.sort(key=lambda t: t[0], reverse=True)
    out = [c for _, c in scored[:top_k]]
    cache.set(key, out, 60*10)
    return out

def session_aware_recs(user, current_listing, candidates, top_k=8) -> List[Any]:
    try:
        uid = getattr(user, "user_id", None) or getattr(user, "id", None)
        recent = cache.get(f"recent:{uid}") or []
        if current_listing:
            lid = getattr(current_listing, "listing_id", None)
            if lid:
                recent = [lid] + [x for x in recent if x != lid]
                recent = recent[:10]
                cache.set(f"recent:{uid}", recent, 60*60)
        base = recommend_similar_listings(current_listing, candidates, top_k=top_k*2)
        # Boost by recency overlap in features
        boost = {}
        for c in base:
            s = 0.0
            try:
                for r in recent:
                    # lightweight similarity to each recent viewed
                    # fallback: same make/model/year
                    s += (1.0 if getattr(c.car, "make", "") == getattr(current_listing.car, "make", "") else 0.0)
                boost[c.listing_id] = s
            except Exception:
                boost[getattr(c, "listing_id", None)] = 0.0
        scored = []
        v0 = listing_feature_vector(current_listing)
        for c in (base or candidates):
            try:
                if getattr(c, "listing_id", None) == getattr(current_listing, "listing_id", None):
                    continue
                v = listing_feature_vector(c)
                s = _cosine(v0, v) + 0.05*boost.get(getattr(c, "listing_id", None), 0.0)
                scored.append((s, c))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0], reverse=True)
        return [c for _, c in scored[:top_k]]
    except Exception:
        return recommend_similar_listings(current_listing, candidates, top_k=top_k)

def collaborative_recs(user, all_listings, top_k=8) -> List[Any]:
    try:
        from .models import ActivityLog, Message, Transaction, TestDrive
        # Build implicit interactions for this user
        user_items = set()
        try:
            acts = ActivityLog.objects.filter(user=user, action__icontains="Viewed listing").order_by("-created_at")[:200]
            for a in acts:
                # extract listing_id from path if present
                p = getattr(a, "path", "") or ""
                if "/listings/" in p:
                    try:
                        part = p.split("/listings/")[1].split("/")[0]
                        user_items.add(part)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            msgs = Message.objects.filter(sender=user).exclude(listing__isnull=True)
            for m in msgs:
                user_items.add(str(getattr(m.listing, "listing_id", "")))
        except Exception:
            pass
        try:
            trs = Transaction.objects.filter(buyer=user)
            for t in trs:
                user_items.add(str(getattr(t.listing, "listing_id", "")))
        except Exception:
            pass
        try:
            drives = TestDrive.objects.filter(buyer=user)
            for d in drives:
                user_items.add(str(getattr(d.listing, "listing_id", "")))
        except Exception:
            pass
        # Co-visitation: find other users with overlap and aggregate their items
        neighbors = set()
        try:
            for lid in list(user_items)[:50]:
                like_logs = ActivityLog.objects.filter(path__icontains=str(lid))
                for l in like_logs:
                    neighbors.add(l.user_id)
        except Exception:
            pass
        neighbor_items = {}
        try:
            for nid in list(neighbors)[:200]:
                logs = ActivityLog.objects.filter(user_id=nid, action__icontains="Viewed listing").order_by("-created_at")[:200]
                for a in logs:
                    p = getattr(a, "path", "") or ""
                    if "/listings/" in p:
                        try:
                            part = p.split("/listings/")[1].split("/")[0]
                            neighbor_items[part] = neighbor_items.get(part, 0) + 1
                        except Exception:
                            pass
        except Exception:
            pass
        scored = []
        for lst in all_listings:
            lid = str(getattr(lst, "listing_id", ""))
            if lid in user_items:
                continue
            s = neighbor_items.get(lid, 0)
            if s > 0:
                scored.append((s, lst))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [c for _, c in scored[:top_k]]
    except Exception:
        return []

def dealer_matches_for_buyer(city: str, listings_qs, showrooms_qs, top_k=5) -> List[Dict[str, Any]]:
    city = (city or "").strip().lower()
    counts = {}
    for lst in listings_qs:
        sh = getattr(lst, "showroom", None)
        if sh and getattr(sh, "name", None):
            counts[sh.name] = counts.get(sh.name, 0) + 1
    results = []
    for sh in showrooms_qs:
        name = getattr(sh, "name", "")
        rating = 4.2
        try:
            seller = getattr(sh, "seller", None)
            rating = getattr(seller, "seller_profile", None) and getattr(seller.seller_profile, "rating", 4.2) or 4.2
        except Exception:
            pass
        city_match = 1.0 if (getattr(sh, "city", "").strip().lower() == city) else 0.3
        car_count = counts.get(name, 0)
        car_score = min(1.0, car_count / 10.0)
        score = (float(rating)/5.0)*0.4 + city_match*0.3 + car_score*0.3
        results.append({"showroom": sh, "score": score})
    results.sort(key=lambda d: d["score"], reverse=True)
    return results[:top_k]

def price_fairness_info(current, candidates) -> Dict[str, Any]:
    try:
        make = getattr(current.car, "make", "")
        model = getattr(current.car, "model", "")
        year = getattr(current.car, "year", 0)
        prices = []
        for c in candidates:
            if getattr(c.car, "make", "") == make and getattr(c.car, "model", "") == model:
                y = getattr(c.car, "year", 0)
                if abs(int(y) - int(year)) <= 1:
                    p = float(getattr(c, "price", 0) or 0)
                    if p > 0:
                        prices.append(p)
        if not prices:
            for c in candidates:
                if getattr(c.car, "body_type", "") == getattr(current.car, "body_type", ""):
                    p = float(getattr(c, "price", 0) or 0)
                    if p > 0:
                        prices.append(p)
        if not prices:
            return {"label": "Unknown", "median": None, "diff_pct": None}
        prices.sort()
        n = len(prices)
        if n % 2 == 0:
            mid = (prices[(n // 2) - 1] + prices[n // 2]) / 2
        else:
            mid = prices[n // 2]
        cp = float(getattr(current, "price", 0) or 0)
        diff = ((cp - mid) / mid) if mid else 0.0
        if abs(diff) <= 0.05:
            lab = "Fair Price"
        elif diff > 0.10:
            lab = "Expensive"
        elif diff < -0.10:
            lab = "Good Deal"
        else:
            lab = "Slightly Off"
        return {"label": lab, "median": mid, "diff_pct": diff}
    except Exception:
        return {"label": "Unknown", "median": None, "diff_pct": None}

def sentiment_analyze(text: str) -> Optional[float]:
    try:
        from transformers import pipeline
        model_name = os.environ.get("HF_SENTIMENT_MODEL", "distilbert-base-uncased-finetuned-sst-2-english")
        pipe = pipeline("sentiment-analysis", model=model_name)
        res = pipe(text[:512])[0]
        label = res.get("label", "NEUTRAL").upper()
        score = float(res.get("score", 0.5))
        return score if label.startswith("POS") else (-score)
    except Exception:
        t = (text or "").lower()
        if any(w in t for w in ["bad","angry","frustrated","annoyed","hate"]): return -0.6
        if any(w in t for w in ["good","great","love","nice","awesome"]): return 0.6
        return 0.0

def sentiment_analyze_multilingual(text: str) -> Dict[str, Any]:
    try:
        from transformers import pipeline
        model_name = os.environ.get("HF_SENTIMENT_MULTI", "cardiffnlp/twitter-xlm-roberta-base-sentiment")
        pipe = pipeline("sentiment-analysis", model=model_name, tokenizer=model_name)
        res = pipe(text[:512])[0]
        return {"label": res.get("label","NEUTRAL"), "score": float(res.get("score",0.5))}
    except Exception:
        return {"label":"NEUTRAL","score":0.0}

def toxicity_detect(text: str) -> Optional[float]:
    try:
        from transformers import pipeline
        model_name = os.environ.get("HF_TOXICITY_MODEL", "unitary/unbiased-toxic-roberta")
        pipe = pipeline("text-classification", model=model_name)
        res = pipe(text[:512])[0]
        label = (res.get("label", "non-toxic") or "").strip().lower().replace("_", " ")
        score = float(res.get("score",0.0))
        if any(s in label for s in ["non-toxic", "non toxic", "not toxic", "clean"]):
            return 0.0
        if "toxic" in label or "insult" in label or "threat" in label or "obscene" in label or "abuse" in label:
            return score
        return 0.0
    except Exception:
        t = (text or "").lower()
        return 0.7 if any(w in t for w in ["idiot","stupid","hate","abuse"]) else 0.0

def image_condition_score(image_paths: List[str]) -> Optional[float]:
    try:
        import torch
        from PIL import Image
        from transformers import CLIPProcessor, CLIPModel
        model_name = os.environ.get("HF_CLIP_MODEL", "openai/clip-vit-base-patch32")
        model = CLIPModel.from_pretrained(model_name)
        processor = CLIPProcessor.from_pretrained(model_name)
        labels = ["damaged car","rust","clean interior","good condition"]
        scores = []
        for p in image_paths[:12]:
            try:
                img = Image.open(p).convert("RGB")
                inputs = processor(text=labels, images=img, return_tensors="pt", padding=True)
                outputs = model(**inputs)
                logits = outputs.logits_per_image.squeeze().tolist()
                cond = max(logits[2], logits[3]) - max(logits[0], logits[1])
                score = 5.0 + cond
                score = max(0.0, min(10.0, score))
                scores.append(score)
            except Exception:
                continue
        if scores:
            return sum(scores)/len(scores)
        return None
    except Exception:
        return None

def detect_damage_details(image_paths: List[str]) -> Dict[str, Any]:
    out = {"dent_score": None, "scratch_score": None, "notes": ""}
    try:
        import torch
        from PIL import Image
        from transformers import CLIPProcessor, CLIPModel
        model_name = os.environ.get("HF_CLIP_MODEL", "openai/clip-vit-base-patch32")
        model = CLIPModel.from_pretrained(model_name)
        processor = CLIPProcessor.from_pretrained(model_name)
        dent_scores = []
        scratch_scores = []
        for p in image_paths[:12]:
            try:
                img = Image.open(p).convert("RGB")
                labels = ["car dent","car scratch","good paint","clean body"]
                inputs = processor(text=labels, images=img, return_tensors="pt", padding=True)
                outputs = model(**inputs)
                logits = outputs.logits_per_image.squeeze().tolist()
                dent = logits[0] - max(logits[2], logits[3])
                scratch = logits[1] - max(logits[2], logits[3])
                dent_scores.append(dent)
                scratch_scores.append(scratch)
            except Exception:
                continue
        if dent_scores:
            out["dent_score"] = max(0.0, min(1.0, sum(dent_scores)/len(dent_scores)))
        if scratch_scores:
            out["scratch_score"] = max(0.0, min(1.0, sum(scratch_scores)/len(scratch_scores)))
        out["notes"] = "Scores are heuristic via CLIP; higher indicates more probable damage."
        return out
    except Exception:
        return out

def chatbot_query(question: str, listings_qs) -> str:
    q = (question or "").strip().lower()
    if not q:
        return "Please ask your car query, for example: 'SUV under 20 lakh in Ahmedabad'."

    def _rank_sellers(rows):
        by_seller = {}
        for lst in rows:
            try:
                seller = getattr(lst, "seller", None)
                if not seller:
                    continue
                sid = str(getattr(seller, "user_id", None) or getattr(seller, "id", ""))
                if sid not in by_seller:
                    by_seller[sid] = {
                        "seller": seller,
                        "count": 0,
                        "sum_price": 0.0,
                        "rating": 0.0,
                        "dealership_name": "",
                    }
                by_seller[sid]["count"] += 1
                by_seller[sid]["sum_price"] += float(getattr(lst, "price", 0) or 0)
            except Exception:
                continue

        profiles = {}
        try:
            from .models import Seller
            q = Seller.objects.filter(user_id__in=list(by_seller.keys()))
            profiles = {str(p.user_id): p for p in q}
        except Exception:
            profiles = {}

        ranked = []
        for sid, d in by_seller.items():
            count = int(d["count"])
            prof = profiles.get(sid)
            rating = float(getattr(prof, "rating", 0) or 0) if prof else float(d["rating"])
            dealership_name = (getattr(prof, "dealership_name", "") or "") if prof else ""
            avg_price = (d["sum_price"] / count) if count else 0.0
            ranked.append({
                "seller": d["seller"],
                "count": count,
                "rating": rating,
                "avg_price": avg_price,
                "dealership_name": dealership_name,
            })
        ranked.sort(key=lambda x: (x["rating"], x["count"], -x["avg_price"]), reverse=True)
        return ranked

    if any(k in q for k in ["best seller", "top seller", "which seller", "seller is best", "good seller"]):
        ranked = _rank_sellers(listings_qs)
        if not ranked:
            return "I couldn't find enough seller data yet."
        top = ranked[0]
        s = top["seller"]
        best_name = (
            top.get("dealership_name")
            or getattr(s, "name", None)
            or getattr(s, "email", "Top seller")
        )
        lines = [
            f"Best seller right now: {best_name}",
            f"Rating: {top['rating']:.2f}/5, Active listings: {top['count']}",
        ]
        if len(ranked) > 1:
            lines.append("Other strong sellers:")
            for row in ranked[1:4]:
                s2 = row["seller"]
                name2 = (
                    row.get("dealership_name")
                    or getattr(s2, "name", None)
                    or getattr(s2, "email", "Seller")
                )
                lines.append(f"- {name2}: {row['rating']:.2f}/5 ({row['count']} listings)")
        return "\n".join(lines)

    try:
        groq_key = os.environ.get("GROQ_API_KEY","")
        if groq_key:
            import requests
            model = os.environ.get("GROQ_MODEL","llama-3.3-70b-versatile")
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant for car buyers in India."},
                    {"role": "user", "content": question or ""}
                ],
                "temperature": 0.3,
                "max_tokens": 512
            }
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            r = requests.post(url, json=payload, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            txt = (((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if txt:
                return txt.strip()
        from langchain.prompts import ChatPromptTemplate
        from langchain_community.llms import Ollama
        llm = Ollama(model=os.environ.get("OLLAMA_MODEL","llama3.1"))
        prompt = ChatPromptTemplate.from_messages([("system","You are a helpful assistant for car buyers in India."),("human","{query}")])
        chain = prompt | llm
        out = chain.invoke({"query": question})
        return str(out).strip() if out else ""
    except Exception:
        import re
        ql = (question or "").lower()
        units = {"cr": 10000000.0, "crore": 10000000.0, "crores": 10000000.0, "lakh": 100000.0, "lakhs": 100000.0, "k": 1000.0, "thousand": 1000.0}
        def to_amount(s):
            s = s.strip().lower()
            m = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*(cr|crore|crores|lakh|lakhs|k|thousand)?", s)
            if not m:
                return None
            val = float(m.group(1))
            u = m.group(2) or ""
            mul = units.get(u, 1.0)
            if not m.group(2) and val < 50:
                mul = 100000.0
            return val * mul
        min_price = None
        max_price = None
        m = re.search(r"(between|from)\s+([0-9\.]+\s*(?:cr|crore|crores|lakh|lakhs|k|thousand)?)\s*(?:to|and|-)\s*([0-9\.]+\s*(?:cr|crore|crores|lakh|lakhs|k|thousand)?)", ql)
        if m:
            a = to_amount(m.group(2))
            b = to_amount(m.group(3))
            lo = min(a or 0, b or 0)
            hi = max(a or 0, b or 0)
            min_price = lo or None
            max_price = hi or None
        else:
            m2 = re.search(r"(above|over|greater\s+than|more\s+than|min(?:imum)?)\s+([0-9\.]+\s*(?:cr|crore|crores|lakh|lakhs|k|thousand)?\+?)", ql)
            if m2:
                amt = m2.group(2).replace("+","").strip()
                min_price = to_amount(amt)
            m3 = re.search(r"(under|below|less\s+than|max(?:imum)?)\s+([0-9\.]+\s*(?:cr|crore|crores|lakh|lakhs|k|thousand)?)", ql)
            if m3:
                max_price = to_amount(m3.group(2))
            if not min_price and "+" in ql:
                pm = re.search(r"([0-9\.]+\s*(?:cr|crore|crores|lakh|lakhs|k|thousand)?)\s*\+", ql)
                if pm:
                    min_price = to_amount(pm.group(1))
        body = None
        if "suv" in ql: body = "SUV"
        elif "sedan" in ql: body = "Sedan"
        elif "hatch" in ql: body = "Hatchback"
        elif "mpv" in ql: body = "MPV"
        elif "coupe" in ql: body = "Coupe"
        fuel = None
        if "diesel" in ql: fuel = "Diesel"
        elif "petrol" in ql: fuel = "Petrol"
        elif "electric" in ql or "ev" in ql: fuel = "Electric"
        elif "cng" in ql: fuel = "CNG"
        city = None
        ci = re.search(r"\bin\s+([a-zA-Z ]+)", ql)
        if ci:
            city = ci.group(1).strip().title()
        res = []
        for lst in listings_qs:
            try:
                p = float(getattr(lst, "price", 0) or 0)
                if min_price and p < min_price:
                    continue
                if max_price and p > max_price:
                    continue
                if body and (getattr(lst.car, "body_type", "") or "").strip().lower() != body.lower():
                    continue
                if fuel and (getattr(lst.car, "fuel_type", "") or "").strip().lower() != fuel.lower():
                    continue
                if city:
                    sh = getattr(lst, "showroom", None)
                    cval = getattr(sh, "city", "") if sh else ""
                    if not cval or cval.strip().lower() != city.strip().lower():
                        continue
                res.append(lst)
            except Exception:
                continue
        if not res:
            return "No exact matches found for your criteria."
        res = sorted(res, key=lambda x: float(getattr(x, "price", 0) or 0), reverse=True if min_price and not max_price else False)
        lines = []
        for l in res[:5]:
            try:
                amt = float(getattr(l, "price", 0) or 0)
                lines.append(f"- {l.car.make} {l.car.model} ({l.car.year}) — ₹{amt:,.0f}")
            except Exception:
                continue
        return "Top suggestions:\n" + "\n".join(lines)
