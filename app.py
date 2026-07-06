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
    weekday_pref_txt = st.text_input("（任意）曜日を優先するメンバー", "")
    st.caption("例: A:月, C:金:宿直 → Aは月曜、Cは金曜の宿直を優先。書式は「氏名:曜日」または「氏名:曜日:枠種別」。")
    with st.expander("詳細設定（任意）"):
        top_coeff = st.slider("最新年度の係数（傾斜の強さ）", 1.0, 3.0, 2.0, 0.1)
        hol_oc = st.number_input("祝日(平日)の夜OCの点数", 1, 9, 3)
        hol_duty = st.number_input("祝日(平日)の当直の点数", 1, 9, 4)
        st.markdown("**土日祝のOCが1枠(終日)のときの点数**")
        oc_s_sat = st.number_input("土曜 終日OC", 1, 9, 3)
        oc_s_sun = st.number_input("日曜 終日OC(翌月曜が平日)", 1, 9, 2)
        oc_s_sun_mh = st.number_input("日曜 終日OC(翌月曜が祝日)", 1, 9, 3)
        oc_s_hol = st.number_input("祝日(平日) 終日OC", 1, 9, 3)
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


def parse_weekday_pref(txt):
    rules = []
    for part in txt.split(","):
        seg = [s.strip() for s in part.split(":") if s.strip()]
        if len(seg) >= 2:
            r = {"member": seg[0], "weekday": seg[1]}
            if len(seg) >= 3:
                r["kind"] = seg[2]
            rules.append(r)
    return rules


def solve_params():
    return dict(
        duty_pref={m.strip(): "day" for m in extra_pref.split(",") if m.strip()},
        weekday_prefer=parse_weekday_pref(weekday_pref_txt),
        holiday_wd_oc=int(hol_oc), holiday_wd_duty=int(hol_duty),
        oc_single_sat=int(oc_s_sat), oc_single_sun=int(oc_s_sun),
        oc_single_sun_monhol=int(oc_s_sun_mh), oc_single_holiday=int(oc_s_hol),
        top_coeff=float(top_coeff), w_premium=int(w_premium), w_consec=int(w_consec),
        w_spacing=int(w_spacing),
        spacing={"OC": int(sp_oc), "宿直": int(sp_shuku), "日直": int(sp_nikki)},
        spacing_cross={"宿直-日直": int(sp_sd), "OC-宿直": int(sp_oshuku), "OC-日直": int(sp_onikki)},
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
