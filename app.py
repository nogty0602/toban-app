"""当直表作成アプリ（Streamlit）
起動: python -m streamlit run app.py
"""
import io
import datetime
import pandas as pd
import streamlit as st
from duty_solver import solve_roster, template_info, apply_photo_grid
from photo_reader import read_photo
from wish_builder import build_wish_sheet

st.set_page_config(page_title="当直表作成", page_icon="🗓️", layout="wide")
st.title("🗓️ 当直表 自動作成")

with st.sidebar:
    st.header("設定")
    today = datetime.date.today()
    nxt = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    year = st.number_input("年", 2020, 2100, nxt.year)
    month = st.number_input("月（表の中身の月）", 1, 12, nxt.month)
    extra_pref = st.text_input("（任意）日直を優先するメンバー", "")
    weekday_pref_txt = st.text_area("（任意）曜日を優先するメンバー", "", height=68)
    st.caption("複数の指定は「;」か改行で区切る。書式「氏名:曜日」。第N週は数字、複数可。枠種別も任意。"
               "\n例: A:土2,4 → Aは第2・第4土曜を優先。C:金2:宿直 → Cは第2金曜の宿直。B:土 → Bは毎週土曜。")
    with st.expander("詳細設定（任意）"):
        top_coeff = st.slider("最新年度の係数（傾斜の強さ）", 1.0, 3.0, 2.0, 0.1)
        w_duty_slope = st.number_input("当直/日直の回数傾斜の強さ", 0, 200, 15)
        st.caption("大きいほど、当直・日直の“回数”を新しい人に多く寄せます（0で無効）。")
        hol_oc = st.number_input("祝日(平日)の夜OCの点数", 1, 9, 3)
        hol_duty = st.number_input("祝日(平日)の当直の点数", 1, 9, 4)
        st.markdown("**土日祝のOCが1枠(終日)のときの点数**")
        oc_s_sat = st.number_input("土曜 終日OC", 1, 9, 3)
        oc_s_sun = st.number_input("日曜 終日OC(翌月曜が平日)", 1, 9, 2)
        oc_s_sun_mh = st.number_input("日曜 終日OC(翌月曜が祝日)", 1, 9, 3)
        oc_s_hol = st.number_input("祝日(平日) 終日OC", 1, 9, 3)
        st.markdown("**入局年度による当直ルール（空欄＝無効）**")
        no_sat_year = st.text_input("土曜当直を外す：入局年度がこれより古い人", "")
        st.caption("例: 2015 → 2014年以前入局の人は土曜の宿直に入れない。")
        jr_year = st.text_input("金土当直を優先：入局年度がこれより新しい人", "")
        st.caption("例: 2018 → 2019年以降入局の人に金曜・土曜の宿直を優先。")
        sen_cap_year = st.text_input("日直＋当直の回数制限：入局年度がこれより古い人", "")
        sen_cap = st.number_input("↑その人たちの日直＋当直の上限回数", 0, 4, 1)
        st.caption("例: 2010 & 上限1 → 2009年以前入局の人は日直＋当直あわせて1回まで。")
        w_frisat = st.number_input("↑金土優先の重み", 0, 500, 40)
        w_premium = st.number_input("④プレミアム枠超過の重み", 0, 500, 80)
        w_consec = st.number_input("③連続勤務の重み", 0, 500, 100)
        st.markdown("**同じ種別をあける日数（1＝無効）**")
        sp_oc = st.number_input("オンコールの間隔", 1, 31, 1)
        sp_shuku = st.number_input("当直(宿直)の間隔", 1, 31, 7)
        sp_nikki = st.number_input("日直の間隔", 1, 31, 7)
        st.markdown("**種別をまたいであける日数（1＝無効）**")
        sp_sd = st.number_input("当直と日直の間隔", 1, 31, 1)
        sp_oshuku = st.number_input("オンコールと当直の間隔", 1, 31, 1)
        sp_onikki = st.number_input("オンコールと日直の間隔", 1, 31, 1)
        w_spacing = st.number_input("あけられない場合の重み", 0, 500, 120)
        time_limit = st.number_input("計算時間上限（秒）", 5, 300, 40)


def parse_weekday_rules(txt):
    """例: 'A:土2,4 ; C:金2:宿直 ; B:土' → ルール一覧。区切りは ; または 改行。"""
    rules = []
    for part in txt.replace("\n", ";").split(";"):
        seg = [s.strip() for s in part.split(":") if s.strip()]
        if len(seg) < 2:
            continue
        member = seg[0]
        wtoken = seg[1].replace("，", ",")
        wd = wtoken[0]                      # 先頭1文字が曜日
        weeks = [int(x) for x in wtoken[1:].split(",") if x.strip().isdigit()] or None
        r = {"member": member, "weekday": wd, "weeks": weeks}
        if len(seg) >= 3:
            r["kind"] = seg[2]
        rules.append(r)
    return rules


def solve_params():
    return dict(
        duty_pref={m.strip(): "day" for m in extra_pref.split(",") if m.strip()},
        weekday_prefer=parse_weekday_rules(weekday_pref_txt),
        holiday_wd_oc=int(hol_oc), holiday_wd_duty=int(hol_duty),
        oc_single_sat=int(oc_s_sat), oc_single_sun=int(oc_s_sun),
        oc_single_sun_monhol=int(oc_s_sun_mh), oc_single_holiday=int(oc_s_hol),
        top_coeff=float(top_coeff), w_premium=int(w_premium), w_consec=int(w_consec),
        w_duty_slope=int(w_duty_slope),
        w_spacing=int(w_spacing),
        spacing={"OC": int(sp_oc), "宿直": int(sp_shuku), "日直": int(sp_nikki)},
        spacing_cross={"宿直-日直": int(sp_sd), "OC-宿直": int(sp_oshuku), "OC-日直": int(sp_onikki)},
        no_sat_duty_year=(int(no_sat_year) if no_sat_year.strip().isdigit() else None),
        jr_frisat_year=(int(jr_year) if jr_year.strip().isdigit() else None),
        senior_duty_cap_year=(int(sen_cap_year) if sen_cap_year.strip().isdigit() else None),
        senior_duty_cap=int(sen_cap),
        w_frisat=int(w_frisat),
        time_limit=int(time_limit))


def show_result(data, summary, info):
    st.success(f"完成しました（{info['status']}）")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("枠数", info["n_slots"]); c2.metric("総スコア", info["total_points"])
    c3.metric("連続勤務", info["consecutive"]); c4.metric("祝日", ", ".join(info["holidays"]) or "なし")
    df = pd.DataFrame(summary).rename(columns={
        "member": "メンバー", "year": "入局", "coeff": "係数", "pref": "希望",
        "target": "目標pt", "points": "実pt", "oc": "OC", "duty": "当直", "premium": "プレミアム"})
    st.subheader("メンバー別サマリー")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.bar_chart(df.set_index("メンバー")[["目標pt", "実pt"]])
    over = df[df["プレミアム"] > 1]["メンバー"].tolist()
    if over:
        st.warning(f"④プレミアム枠が2回以上: {', '.join(over)}（重みで調整可）")
    if info.get("missing_year"):
        st.warning(f"入局年度が空欄: {', '.join(info['missing_year'])}"
                   "（中央値で仮計算しました。正しい年度を入れると傾斜が正確になります）")
    st.download_button("⬇ 当直表をダウンロード", data=data,
                       file_name=f"当直表_{year}年{month}月.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


mode = st.radio("入力方法", ["Excelの希望表", "写真＋Excelテンプレ", "割り振り→希望表を作成"], horizontal=True)

# ========== モードC: 割り振り→希望表 ==========
if mode == "割り振り→希望表を作成":
    st.caption("各科の割り振りExcelから、その月の希望表(印刷用)を作成します。氏名・入局年度はベーステンプレから引き継ぎます。")
    alloc = st.file_uploader("① 各科の割り振り（.xlsx）", type=["xlsx"], key="alloc")
    base = st.file_uploader("② ベースの希望表テンプレ（氏名・入局年度）", type=["xlsx"], key="base")
    uro = st.text_input("自科（当直担当）を表す語", "ウロ")
    if alloc and base and st.button("▶ 希望表を作成", type="primary"):
        try:
            data, info = build_wish_sheet(alloc, base, uro_prefix=uro.strip() or "ウロ")
        except Exception as e:
            st.error(f"作成できませんでした: {e}")
        else:
            st.success(f"{info['year']}年{info['month']}月の希望表を作成しました（枠数 {info['n_slots']}）")
            c1, c2, c3 = st.columns(3)
            c1.metric("枠数", info["n_slots"]); c2.metric("人数", len(info["members"]))
            c3.metric("祝日", ", ".join(info["holidays"]) or "なし")
            st.download_button("⬇ 希望表をダウンロード", data=data,
                               file_name=f"希望表_{info['year']}年{info['month']}月.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.caption("この希望表を印刷して×を記入 → 「写真＋Excelテンプレ」または「Excelの希望表」モードで当直表を作成できます。")

# ========== モードA: Excel ==========
elif mode == "Excelの希望表":
    up = st.file_uploader("希望表をアップロード（.xlsx）", type=["xlsx"])
    if up is not None and st.button("▶ 当直表を作成", type="primary"):
        try:
            with st.spinner("計算中…"):
                data, summary, info = solve_roster(up, int(year), int(month), **solve_params())
        except Exception as e:
            st.error(f"作成できませんでした: {e}")
        else:
            show_result(data, summary, info)

# ========== モードB: 写真 ==========
else:
    st.caption("四隅マーク付きの用紙を、なるべく真上から撮影／スキャンした画像を使ってください。")
    tpl = st.file_uploader("① Excelテンプレ（枠・氏名・年度）", type=["xlsx"], key="tpl")
    photo = st.file_uploader("② 手書き希望表の写真", type=["png", "jpg", "jpeg"], key="photo")

    if tpl and photo and st.button("写真を読み取る"):
        try:
            tpl_bytes = tpl.getvalue()
            members, years, slots = template_info(io.BytesIO(tpl_bytes))
            grid, preview = read_photo(photo.getvalue(), n_cols=len(members))
            if len(slots) != len(grid):
                st.warning(f"テンプレの枠数({len(slots)})と写真の行数({len(grid)})が一致しません。"
                           "テンプレが同じ様式か確認してください。")
            st.session_state["ph"] = dict(tpl_bytes=tpl_bytes, members=members,
                                          slots=slots, grid=grid, preview=preview)
        except Exception as e:
            st.error(f"読み取りに失敗しました: {e}")

    ph = st.session_state.get("ph")
    if ph:
        st.image(ph["preview"], caption="緑＝×と読み取ったマス", use_container_width=True)
        labels = [f"{d}{wd} {kind}" for (_, d, wd, kind) in ph["slots"]]
        # 同名メンバーは表示だけ区別（例: T.K → T.K#1, T.K#2）。並び順で書き戻すので実害なし。
        seen = {}; disp = []
        for m in ph["members"]:
            seen[m] = seen.get(m, 0) + 1
            disp.append(f"{m}#{seen[m]}" if ph["members"].count(m) > 1 else m)
        n = min(len(labels), len(ph["grid"]))
        df = pd.DataFrame(ph["grid"][:n], columns=disp, index=labels[:n]).astype(bool)
        st.caption("チェック＝×（勤務不可）。誤読はクリックで修正できます。")
        edited = st.data_editor(df, use_container_width=True, height=520)
        if st.button("▶ この内容で当直表を作成", type="primary"):
            try:
                new_grid = edited.astype(int).values.tolist()
                filled = apply_photo_grid(io.BytesIO(ph["tpl_bytes"]), new_grid)
                with st.spinner("計算中…"):
                    data, summary, info = solve_roster(io.BytesIO(filled), int(year), int(month), **solve_params())
            except Exception as e:
                st.error(f"作成できませんでした: {e}")
            else:
                show_result(data, summary, info)
