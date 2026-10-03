"""Read-only measurement for issue #514 (wayfinder map #510).

Downloads CVM's FI lamina monthly zips (and the HIST folder), folds every
lamina to the latest one per CNPJ and prints aggregates only. It writes
nothing to any database and holds no secret. Public CVM files in, log lines out.

Universe file (.github/research/lamina_universe.txt), one fund per line:
  cnpj14|A or B|D or N|pl_reais|e8|e7
  A = PL >= R$1M at its latest month in fact_fund_monthly, B = below.
  D = the fund reported NAV in cvm_fi_diario in 2026-09, N = it did not.
  e8 / e7 = the balancete-derived annual fee estimate in percent for 2026-08 /
  2026-07 (monthly flow of the accumulated 81781001 account, times 12, over the
  month's PL); empty when it could not be derived.
"""
import collections
import concurrent.futures as cf
import copy
import csv
import hashlib
import io
import json
import re
import statistics
import sys
import time
import urllib.request
import zipfile

BASE = "https://dados.cvm.gov.br/dados/FI/DOC/LAMINA/DADOS/"
REF = (2026, 8)  # the newest file; ages are measured against it, not against today
DEMO = ["42592315000115", "50088190000119", "35377390000106", "51488342000133", "08935128000159"]
csv.field_size_limit(sys.maxsize)
FAILED = []


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "silo-research/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception as exc:  # retried, then recorded and printed; never swallowed
            last = exc
            time.sleep(3 * (i + 1))
    FAILED.append((url, f"{type(last).__name__}: {last}"))
    return None


def norm(c):
    return re.sub(r"\D", "", c or "").zfill(14)


def num(x):
    x = (x or "").strip()
    if not x:
        return None
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def months_between(dt):
    y, m = int(dt[:4]), int(dt[5:7])
    return (REF[0] - y) * 12 + (REF[1] - m)


def pct(vals, ps=(10, 25, 50, 75, 90, 99)):
    v = sorted(vals)
    if not v:
        return {}
    out = {}
    for p in ps:
        k = min(len(v) - 1, max(0, int(round(p / 100 * (len(v) - 1)))))
        out[f"p{p}"] = round(v[k], 4)
    out["n"] = len(v)
    return out


def buckets(ages):
    b = collections.OrderedDict([("0", 0), ("1-3", 0), ("4-12", 0), ("13-24", 0), (">24", 0)])
    for a in ages:
        if a <= 0:
            b["0"] += 1
        elif a <= 3:
            b["1-3"] += 1
        elif a <= 12:
            b["4-12"] += 1
        elif a <= 24:
            b["13-24"] += 1
        else:
            b[">24"] += 1
    return dict(b)


def decode(raw):
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def list_zips(url, pattern):
    blob = get(url)
    if blob is None:
        return []
    return sorted(set(re.findall(pattern, blob.decode("utf-8", "replace"))))


class Store:
    """Latest lamina per CNPJ: latest_rows (all rows at the newest DT_COMPTC) and
    latest_fee (newest row with a parsable TAXA_ADM)."""

    def __init__(self):
        self.latest_rows = {}
        self.latest_fee = {}
        self.first_seen = {}

    def add(self, c, dt, row):
        cur = self.latest_rows.get(c)
        if cur is None or dt > cur[0]:
            self.latest_rows[c] = (dt, [row])
        elif dt == cur[0]:
            cur[1].append(row)
        if c not in self.first_seen or dt < self.first_seen[c]:
            self.first_seen[c] = dt
        if row["taxa_adm"] is not None:
            f = self.latest_fee.get(c)
            if f is None or dt > f[0] or (dt == f[0] and not row["id_sub"] and f[1]["id_sub"]):
                self.latest_fee[c] = (dt, row)


def pick(rows):
    """Prefer the class-level row (empty ID_SUBCLASSE), then the one with a fee."""
    rows = sorted(rows, key=lambda r: (bool(r["id_sub"]), r["taxa_adm"] is None))
    return rows[0]


def main():
    uni = {}
    for line in open(".github/research/lamina_universe.txt"):
        p = line.rstrip("\n").split("|")
        if len(p) < 6:
            continue
        uni[p[0]] = dict(
            band=p[1], diario=p[2], pl=float(p[3]) if p[3] else None,
            e8=float(p[4]) if p[4] else None, e7=float(p[5]) if p[5] else None,
        )
    print(f"UNIVERSE n={len(uni)} A={sum(1 for u in uni.values() if u['band']=='A')} "
          f"D={sum(1 for u in uni.values() if u['diario']=='D')} "
          f"e8={sum(1 for u in uni.values() if u['e8'] is not None)}")

    names = list_zips(BASE, r'href="(lamina_fi_\d{6}\.zip)"')
    hist_names = list_zips(BASE + "HIST/", r'href="([^"/]+\.zip)"')
    print("DADOS files listed:", len(names), names[:1], names[-1:])
    print("HIST files listed:", len(hist_names), hist_names)
    if not names:
        print("FATAL: DADOS index empty"); sys.exit(1)

    ref_header = None
    store = Store()
    month_rows = []
    cols_by_file = {}
    all_cnpj = set()
    year_cnpj = collections.defaultdict(set)
    nonpunct = 0
    punct = 0
    bad_len = 0
    sub_funds_only = 0
    tp_totals = collections.Counter()
    tp_by_month = {}

    def fetch(n):
        return n, get(BASE + n)

    def process(n, blob, grp, st):
        nonlocal ref_header, nonpunct, punct, bad_len
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = z.namelist()
            main = None
            for m in members:
                if m.lower().endswith(".csv") and "carteira" not in m and "rentab" not in m:
                    main = m
                    break
            if main is None:
                print(f"{grp} {n}: no main csv among {members}")
                FAILED.append((n, "no main csv"))
                return
            raw = z.read(main)
            size = len(raw)
        fffd = raw.count(b"\xef\xbf\xbd")
        text, enc = decode(raw)
        rdr = csv.DictReader(io.StringIO(text), delimiter=";")
        cols = rdr.fieldnames or []
        hh = hashlib.md5(";".join(cols).encode()).hexdigest()[:8]
        if grp == "DADOS" and n.endswith("202608.zip"):
            ref_header = cols
        rows = list(rdr)
        m_dt = collections.Counter()
        tp = collections.Counter()
        cn = set()
        keys = collections.Counter()
        taxa = perfm = desp = subs = 0
        cnpj_col = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in cols else next((c for c in cols if "CNPJ" in c), None)
        for r in rows:
            rawc = r.get(cnpj_col) or ""
            if re.fullmatch(r"\d{14}", rawc.strip()):
                nonpunct += 1
            else:
                punct += 1
            c = norm(rawc)
            if len(c) != 14:
                bad_len += 1
            dt = (r.get("DT_COMPTC") or "").strip()
            m_dt[dt[:7]] += 1
            tp[r.get("TP_FUNDO_CLASSE", "?")] += 1
            cn.add(c)
            idsub = (r.get("ID_SUBCLASSE") or "").strip()
            keys[(c, dt, idsub)] += 1
            if idsub:
                subs += 1
            ta = num(r.get("TAXA_ADM"))
            pf = (r.get("TAXA_PERFM") or "").strip()
            pd = num(r.get("PR_PL_DESPESA"))
            taxa += ta is not None
            perfm += bool(pf)
            desp += pd is not None
            if dt:
                st.add(c, dt, dict(
                    cnpj=c, dt=dt, tp=r.get("TP_FUNDO_CLASSE", ""), id_sub=idsub, denom=(r.get("DENOM_SOCIAL") or "").strip()[:70],
                    taxa_adm=ta, tmin=num(r.get("TAXA_ADM_MIN")), tmax=num(r.get("TAXA_ADM_MAX")),
                    tp_taxa=(r.get("TP_TAXA_ADM") or "").strip(), perfm=pf, pr_desp=pd,
                    pl=num(r.get("VL_PATRIM_LIQ")), conv=r.get("QT_DIA_CONVERSAO_COTA_RESGATE"),
                    pagto=r.get("QT_DIA_PAGTO_RESGATE"), src=n,
                ))
        dupkeys = sum(1 for v in keys.values() if v > 1)
        add, rem = [], []
        cols_by_file[n] = cols
        mm = sum(v for k, v in m_dt.items() if k != n[-10:-4][:4] + "-" + n[-10:-4][4:6]) if grp == "DADOS" else sum(m_dt.values())
        month_rows.append(dict(grp=grp, file=n, size=size, enc=enc, fffd=fffd, rows=len(rows), cnpj=len(cn),
                               fi=tp.get("FI", 0), fif=tp.get("CLASSES - FIF", 0),
                               other=len(rows) - tp.get("FI", 0) - tp.get("CLASSES - FIF", 0),
                               taxa=taxa, perfm=perfm, desp=desp, subs=subs, dupkeys=dupkeys,
                               dtmis=mm, hdr=hh, add=add, rem=rem, ncols=len(cols), members=members if grp == "HIST" else None))
        all_cnpj.update(cn) if grp == "DADOS" else None
        if grp == "DADOS":
            year_cnpj[n[10:14]].update(cn)
        for k, v in tp.items():
            tp_totals[k] += v

    t0 = time.time()
    with cf.ThreadPoolExecutor(4) as ex:
        for n, blob in ex.map(fetch, names):
            if blob is None:
                print(f"FAILED {n}")
                continue
            process(n, blob, "DADOS", store)
            print(f"  done {n} {len(blob)} bytes, {time.time()-t0:.0f}s", flush=True)

    ref_header = cols_by_file.get("lamina_fi_202608.zip") or ref_header
    for m in month_rows:
        if ref_header and m["file"] in cols_by_file:
            m["add"] = sorted(set(cols_by_file[m["file"]]) - set(ref_header))
            m["rem"] = sorted(set(ref_header) - set(cols_by_file[m["file"]]))
    print("=" * 80)
    print("PER FILE (DADOS)")
    print("file,size_csv,enc,fffd_bytes,rows,distinct_cnpj,FI,CLASSES-FIF,other,taxa_adm,taxa_perfm,pr_pl_despesa,subclass_rows,dup_keys,dt_mismatch,ncols,hdr,cols_added,cols_removed")
    for m in month_rows:
        print(",".join(str(m[k]) for k in ["file", "size", "enc", "fffd", "rows", "cnpj", "fi", "fif", "other", "taxa", "perfm", "desp", "subs", "dupkeys", "dtmis", "ncols", "hdr"])
              + f",{m['add']},{m['rem']}")
    print("distinct CNPJ over all DADOS files:", len(all_cnpj))
    print("distinct CNPJ per file-year:", {y: len(s) for y, s in sorted(year_cnpj.items())})
    print(f"CNPJ format in DADOS rows: already 14 digits {nonpunct}, punctuated or other {punct}, normalized length != 14: {bad_len}")
    print("TP_FUNDO_CLASSE totals (rows):", dict(tp_totals))
    print("layout hashes:", dict(collections.Counter(m["hdr"] for m in month_rows)))

    # ---- HIST ----
    store_h = copy.deepcopy(store)
    hist_rows = []
    for n in hist_names:
        blob = get(BASE + "HIST/" + n)
        if blob is None:
            print(f"FAILED HIST {n}")
            continue
        before = len(month_rows)
        process(n, blob, "HIST", store_h)
        hist_rows += month_rows[before:]
        print(f"  done HIST {n} {len(blob)} bytes", flush=True)
    for m in hist_rows:
        if ref_header and m["file"] in cols_by_file:
            m["add"] = sorted(set(cols_by_file[m["file"]]) - set(ref_header))
            m["rem"] = sorted(set(ref_header) - set(cols_by_file[m["file"]]))
    print("=" * 80)
    print("PER FILE (HIST)")
    for m in hist_rows:
        print({k: m[k] for k in ["file", "size", "enc", "fffd", "rows", "cnpj", "fi", "fif", "taxa", "perfm", "desp", "subs", "dupkeys", "dtmis", "ncols", "hdr", "add", "rem", "members"]})

    # ---- fold and measure ----
    def fold(st, label):
        print("=" * 80)
        print(f"FOLD {label}: distinct CNPJ with a lamina = {len(st.latest_rows)}, with a parsable TAXA_ADM somewhere = {len(st.latest_fee)}")
        res = collections.OrderedDict()
        cells = collections.defaultdict(lambda: collections.Counter())
        age_all, age_fee = collections.defaultdict(list), collections.defaultdict(list)
        pr_ratio = []
        pr_filled = pr_missing_taxa_present = pr_ge_taxa = 0
        perfm_cls = collections.Counter()
        tp_latest = collections.Counter()
        taxa_vals = []
        flags = collections.Counter()
        sub_only = sub_diff = 0
        for c, u in uni.items():
            for seg in ("ALL", "A", "B", "D", "A&D"):
                if seg == "ALL" or seg == u["band"] or seg == u["diario"] or (seg == "A&D" and u["band"] == "A" and u["diario"] == "D"):
                    k = cells[seg]
                    k["n"] += 1
                    lr = st.latest_rows.get(c)
                    lf = st.latest_fee.get(c)
                    if lr:
                        k["any_lamina"] += 1
                        row = pick(lr[1])
                        a = months_between(lr[0])
                        age_all[seg].append(a)
                        if a <= 12:
                            k["latest_le12m"] += 1
                        if row["taxa_adm"] is not None:
                            k["latest_has_taxa"] += 1
                            if a <= 12:
                                k["latest_has_taxa_le12m"] += 1
                    if lf:
                        k["any_taxa"] += 1
                        a = months_between(lf[0])
                        age_fee[seg].append(a)
                        if a <= 12:
                            k["any_taxa_le12m"] += 1
                        if a <= 24:
                            k["any_taxa_le24m"] += 1
        for seg in ("ALL", "A", "B", "D", "A&D"):
            k = cells[seg]
            print(f"SEG {seg}: " + json.dumps(dict(k)))
            print(f"  age(months) of latest lamina: {json.dumps(pct(age_all[seg]))} buckets {json.dumps(buckets(age_all[seg]))}")
            print(f"  age(months) of latest lamina WITH TAXA_ADM: {json.dumps(pct(age_fee[seg]))} buckets {json.dumps(buckets(age_fee[seg]))}")
        # value quirks, funds in the universe with a latest lamina
        for c, u in uni.items():
            lr = st.latest_rows.get(c)
            if not lr:
                continue
            rows = lr[1]
            row = pick(rows)
            tp_latest[row["tp"]] += 1
            if all(r["id_sub"] for r in rows):
                sub_only += 1
            if len({r["taxa_adm"] for r in rows if r["id_sub"]}) > 1:
                sub_diff += 1
            ta, pd = row["taxa_adm"], row["pr_desp"]
            if pd is not None:
                pr_filled += 1
                if ta is None:
                    pr_missing_taxa_present += 0
            if ta is not None and pd is None:
                pr_missing_taxa_present += 1
            if ta is not None:
                taxa_vals.append(ta)
                flags["taxa_eq0"] += ta == 0
                flags["taxa_lt0.05_gt0"] += 0 < ta < 0.05
                flags["taxa_gt10"] += ta > 10
                flags["tp_" + (row["tp_taxa"] or "empty")] += 1
                if pd is not None and ta > 0:
                    pr_ratio.append(pd / ta)
                    if pd >= ta:
                        pr_ge_taxa += 1
            p = row["perfm"].strip().lower()
            if not p:
                perfm_cls["empty"] += 1
            elif p in ("-", "0", "n/a", "nd", "n/d") or p.startswith(("não há", "nao ha", "não ha", "nao há", "não existe", "não cobra", "não se aplica", "não possui", "n/a")):
                perfm_cls["none_text"] += 1
            elif "crci_" in p or "(descri" in p:
                perfm_cls["template_leak"] += 1
            else:
                perfm_cls["described"] += 1
        print(f"UNIVERSE funds whose latest lamina is class-type: {dict(tp_latest)}")
        print(f"subclass-only latest (no class-level row): {sub_only}; funds whose subclass rows disagree on TAXA_ADM: {sub_diff}")
        print("TAXA_ADM flags (universe, latest lamina with a value):", dict(flags), "n", len(taxa_vals), json.dumps(pct(taxa_vals)))
        print(f"PR_PL_DESPESA filled {pr_filled}; filled where TAXA_ADM absent n/a; TAXA_ADM present but PR_PL_DESPESA absent {pr_missing_taxa_present}")
        print("PR_PL_DESPESA / TAXA_ADM (both >0):", json.dumps(pct(pr_ratio)), "share PR>=TAXA:", round(pr_ge_taxa / max(1, len(pr_ratio)), 3))
        print("TAXA_PERFM text classes (universe latest):", dict(perfm_cls))
        return cells

    fold(store, "DADOS 2019+ only")
    fold(store_h, "DADOS + HIST")

    # ---- CNPJ match ----
    lam = set(store.latest_rows)
    print("=" * 80)
    print(f"CNPJ MATCH: lamina CNPJs (DADOS) {len(lam)}, in universe {len(lam & set(uni))}, not in universe {len(lam - set(uni))}; "
          f"universe funds with no lamina ever: {len(set(uni) - lam)}")

    # ---- comparison against the balancete-derived estimate ----
    print("=" * 80)
    comp_sets = {
        "A, latest lamina <=12m, Fixa, TAXA_ADM>0": lambda r, a, u: u["band"] == "A" and a <= 12 and r["tp_taxa"] == "Fixa" and (r["taxa_adm"] or 0) > 0,
        "A, any lamina age, TAXA_ADM>0": lambda r, a, u: u["band"] == "A" and (r["taxa_adm"] or 0) > 0,
    }
    samples = []
    for label, cond in comp_sets.items():
        for ekey in ("e8", "e7"):
            ratios, diffs = [], []
            for c, u in uni.items():
                lr = store.latest_rows.get(c)
                if not lr or u[ekey] is None:
                    continue
                r = pick(lr[1])
                a = months_between(lr[0])
                if not cond(r, a, u):
                    continue
                ratios.append(u[ekey] / r["taxa_adm"])
                diffs.append(u[ekey] - r["taxa_adm"])
                if label.startswith("A, latest") and ekey == "e8":
                    samples.append((u["pl"] or 0, c, r, a, u))
            n = len(ratios)
            if n:
                w25 = sum(1 for x in ratios if 0.75 <= x <= 1.25) / n
                w50 = sum(1 for x in ratios if 0.5 <= x <= 2.0) / n
                wpp = sum(1 for x in diffs if abs(x) <= 0.25) / n
                print(f"COMPARE [{label}] est={ekey}: n={n} ratio(est/TAXA_ADM) {json.dumps(pct(ratios))} "
                      f"within+-25%={w25:.3f} within x0.5..2={w50:.3f} abs diff<=0.25pp={wpp:.3f} diff(pp) {json.dumps(pct(diffs))}")
            else:
                print(f"COMPARE [{label}] est={ekey}: n=0")
    # Variavel: is the estimate inside [min, max]?
    inside = tot = 0
    for c, u in uni.items():
        lr = store.latest_rows.get(c)
        if not lr or u["e8"] is None or u["band"] != "A":
            continue
        r = pick(lr[1])
        if months_between(lr[0]) <= 12 and r["tp_taxa"] == "Variável" and r["tmin"] is not None and r["tmax"] is not None:
            tot += 1
            inside += (r["tmin"] * 0.75 <= u["e8"] <= r["tmax"] * 1.25)
    print(f"VARIAVEL (A, <=12m): estimate inside [min*0.75, max*1.25]: {inside}/{tot}")
    samples.sort(key=lambda x: -x[0])
    print("SAMPLE (15 largest-PL overlaps): cnpj | denom | dt_comptc | TAXA_ADM | PR_PL_DESPESA | est_aug | est_jul | PL")
    for pl, c, r, a, u in samples[:15]:
        print(f"  {c} | {r['denom']} | {r['dt']} | {r['taxa_adm']} | {r['pr_desp']} | {u['e8']} | {u['e7']} | {pl:.0f}")

    # ---- demo funds ----
    print("=" * 80)
    for c in DEMO:
        lr = store.latest_rows.get(c)
        lf = store.latest_fee.get(c)
        u = uni.get(c)
        if not lr:
            print(f"DEMO {c}: no lamina in DADOS; in universe={bool(u)}")
            continue
        r = pick(lr[1])
        print(f"DEMO {c}: in universe={bool(u)} first_lamina={store.first_seen.get(c)} latest={lr[0]} class_type={r['tp']} id_sub={r['id_sub']!r} "
              f"TAXA_ADM={r['taxa_adm']} min={r['tmin']} max={r['tmax']} tp={r['tp_taxa']} PERFM={r['perfm'][:80]!r} PR_PL_DESPESA={r['pr_desp']} "
              f"conv_resg={r['conv']} pagto_resg={r['pagto']} latest_with_fee={lf[0] if lf else None} est_aug={u['e8'] if u else None}")

    print("=" * 80)
    if FAILED:
        print("FAILED DOWNLOADS/PARSES:")
        for f in FAILED:
            print("  ", f)
    print("DONE", "with failures" if FAILED else "clean")
    sys.exit(1 if FAILED else 0)


main()
