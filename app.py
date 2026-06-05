import streamlit as st
import pandas as pd
import re
from google import genai
from google.genai import types
import os
from PIL import Image

# Load environment variables from .env (if present). Try python-dotenv first,
# otherwise fall back to a simple .env parser so the app still runs.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        os.environ.setdefault(k.strip(), v)
        except Exception:
            pass

import time

def generate_content_with_retries(client, model, contents, config, max_retries=3):
    """Gọi client.models.generate_content và tự động thử lại nếu gặp lỗi quá tải (429) hoặc sập mạng (503)."""
    delay = 2  # Số giây đợi ban đầu trước khi thử lại
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            msg = str(e)
            lower = msg.lower()
            
            # Kiểm tra xem có phải lỗi hết quota (429) hoặc máy chủ quá tải (503) không
            is_quota = 'resource_exhausted' in lower or 'quota' in lower or '429' in lower or 'rate limit' in lower
            is_unavailable = 'unavailable' in lower or '503' in lower or 'high demand' in lower
            
            if (is_quota or is_unavailable) and attempt < max_retries - 1:
                # Đợi một chút rồi thử lại tự động thay vì báo lỗi ngay lập tức
                time.sleep(delay)
                delay *= 2  # Tăng thời gian đợi ở lần sau (Exponential backoff)
                continue
                
            if is_quota:
                retry_message = ''
                m = re.search(r'please retry in\s*([0-9]+(?:\.[0-9]+)?)s', msg, re.IGNORECASE)
                if m:
                    retry_message = f" Vui lòng thử lại sau khoảng {m.group(1)} giây."
                raise RuntimeError(f"API Gemini đang hết quota.{retry_message}\n{msg}") from e
                
            if is_unavailable:
                raise RuntimeError("Máy chủ Gemini hiện đang quá tải do lượng truy cập cao. Hệ thống đã thử lại nhưng chưa thành công, bạn hãy đợi vài giây rồi gõ lại câu hỏi nhé!") from e
            raise
def check_intent_with_ai(client, model, prompt):
    """Sử dụng AI để phân tích xem khách hàng có muốn thêm sản phẩm vào giỏ hay không."""
    try:
        system_instruction = (
            "Bạn là một bộ phân tích ý định người dùng. Nhiệm vụ của bạn là kiểm tra xem "
            "câu nói của người dùng có phải là một lời đồng ý, chấp nhận, hoặc yêu cầu "
            "thêm/bỏ sản phẩm vừa được tư vấn vào giỏ hàng/hộp hàng hay không.\n"
            "Chỉ trả về duy nhất chữ 'YES' nếu họ muốn thêm vào giỏ/chốt đơn.\n"
            "Trả về duy nhất chữ 'NO' nếu câu nói chỉ là mô tả tình trạng da, đặt câu hỏi, "
            "hoặc nói từ 'có' nhưng mang ý nghĩa khác (ví dụ: 'da tớ có mụn', 'có quan trọng không')."
        )
        
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.0, # Để AI trả về kết quả chính xác và nhất quán nhất
            max_output_tokens=5
        )
        
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config
        )
        
        result = response.text.strip().upper()
        return "YES" in result
    except Exception:
        return False
# 1. CẤU HÌNH GIAO DIỆN CHUẨN BEAUTY & COSMETICS
st.set_page_config(page_title="AI Skincare Consultant & Shop", layout="wide")

# Nhúng CSS Custom cao cấp: Phối màu hồng đất chữ trắng toàn diện cho User
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
    
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
        background: linear-gradient(135deg, #fdfbf7 0%, #fef0ef 100%);
    }
    
    /* Làm đẹp các khối chat bong bóng */
    [data-testid="stChatMessage"] {
        border-radius: 16px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.02);
    }
    
    /* Bong bóng chat AI (Trợ lý) */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background-color: rgba(255, 238, 238, 0.8) !important;
        border: 1px solid #fecdd3;
    }
    
    /* Bong bóng chat Bạn (User) - Nền hồng đất chữ trắng chuẩn chỉnh */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: #b2534e !important;
        border: 1px solid #913d39;
    }
    
    /* Ép tất cả các thành phần chữ bên trong bong bóng chat của User phải hiển thị màu trắng rõ nét */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p,
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) li,
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) span,
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) div {
        color: #ffffff !important;
        font-weight: 500 !important;
    }
    
    /* Đồng bộ màu viền của ô nhập liệu bên dưới cho tệp màu hồng đất */
    [data-testid="stChatInput"] {
        border-color: #b2534e !important;
    }
    
    /* Khung viền các thẻ sản phẩm mua hàng */
    .product-card {
        background-color: white;
        padding: 16px;
        border-radius: 12px;
        border: 1px solid #fae8e6;
        box-shadow: 0 4px 10px rgba(0,0,0,0.01);
        margin-bottom: 15px;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# Hàm tính tổng tiền thông minh từ chuỗi (Ví dụ: "250.000đ" -> 250000)
def parse_price(price_str):
    try:
        if pd.isna(price_str) or not price_str:
            return 0
        cleaned = re.sub(r'[^\d]', '', str(price_str))
        return int(cleaned) if cleaned else 0
    except:
        return 0

# 2. ĐỌC DỮ LIỆU EXCEL SẢN PHẨM SẠCH SẼ
def load_data():
    for fname in ["data_san_pham.xlsx", "data san pham.xlsx", "data_san_pham.xlsx"]:
        if os.path.exists(fname):
            try:
                return pd.read_excel(fname)
            except Exception as e:
                st.error(f"⚠️ Lỗi đọc file '{fname}': {e}")
                return pd.DataFrame()
    st.error("⚠️ Không tìm thấy file dữ liệu sản phẩm. Vui lòng đặt file 'data_san_pham.xlsx' cùng thư mục với app.")
    return pd.DataFrame(columns=['Tên sản phẩm', 'Phân loại', 'Chuyên mục ', 'Xuất xứ ', 'Giá tiền', 'Công dụng'])

df_products = load_data()

# 3. KHỞI TẠO BỘ NHỚ LƯU TRỮ (SESSION STATE)
if "messages" not in st.session_state:
    st.session_state.messages = []
if "cart" not in st.session_state:
    st.session_state.cart = []
# Bộ nhớ tinh gọn ẩn: Lưu danh sách các sản phẩm mà AI ĐÃ đề xuất ở lượt chat trước để tự động bốc vào giỏ hàng
if "recommended_products" not in st.session_state:
    st.session_state.recommended_products = []

# Hàm để AI gọi kích hoạt bỏ hàng vào giỏ
def add_product_to_cart(product_names: list[str]):
    """
    Thêm danh sách các sản phẩm vào giỏ hàng của khách hàng.
    """
    added_items = []
    if df_products.empty or 'Tên sản phẩm' not in df_products.columns:
        return "Kho hàng trống."
        
    for p_name_input in product_names:
        match = df_products[df_products['Tên sản phẩm'].str.lower().str.contains(p_name_input.lower(), na=False)]
        if not match.empty:
            actual_name = match.iloc[0]['Tên sản phẩm']
            p_price = match.iloc[0].get('Giá tiền', 'Liên hệ')
            st.session_state.cart.append({"name": actual_name, "price": p_price})
            added_items.append(actual_name)
            
    if added_items:
        return f"Đã tự động thêm thành công: {', '.join(added_items)} vào giỏ hàng."
    return "Không tìm thấy sản phẩm phù hợp trong kho để tự động thêm."

# 4. THIẾT KẾ SIDEBAR BÊN TRÁI
with st.sidebar:
    st.markdown("<h2 style='color: #c05c56;'>📋 Thông Tin Khách Hàng</h2>", unsafe_allow_html=True)
    user_name = st.text_input("Họ và tên:", value="Khách hàng")
    user_age = st.number_input("Tuổi:", min_value=1, max_value=100, value=20)
    user_skin_type = st.selectbox("Loại da hiện tại:", ["Chưa xác định loại da", "Da dầu mụn", "Da khô nhạy cảm", "Da hỗn hợp", "Da thường"])
    
    st.divider()
    
    # Khối Giỏ Hàng tích hợp tính tổng tiền, tổng sản phẩm
    st.markdown("<h2 style='color: #c05c56;'>🛒 Giỏ Hàng Của Bạn</h2>", unsafe_allow_html=True)
    if not st.session_state.cart:
        st.caption("Giỏ hàng hiện đang trống...")
    else:
        total_price = 0
        total_items = len(st.session_state.cart)
        
        for idx, item in enumerate(st.session_state.cart):
            col_item, col_del = st.columns([4, 1])
            col_item.write(f"• **{item['name']}**\n_{item['price']}_")
            total_price += parse_price(item['price'])
            
            if col_del.button("❌", key=f"del_{idx}"):
                st.session_state.cart.pop(idx)
                st.rerun()
                
        st.divider()
        st.markdown(f"📦 **Tổng số lượng:** {total_items} sản phẩm")
        st.markdown(f"💰 **Tổng tiền tạm tính:** <span style='color: #c05c56; font-weight: bold; font-size: 1.2rem;'>{total_price:,}đ</span>", unsafe_allow_html=True)
        st.divider()
        
        st.success("✅ Đã cập nhật sản phẩm mới!")
        if st.button("🔥 Gửi Đơn Đặt Hàng", use_container_width=True):
            st.balloons()
            st.success("Đơn hàng đã được chuyển tới hệ thống xử lý!")
            st.session_state.cart = []
            st.rerun()

    # NÚT CỨU HỘ: Giải phóng bộ nhớ nhanh nếu lỡ tay bấm spam liên tục gây đơ app
    st.divider()
    st.markdown("### ⚙️ Quản Lý Cuộc Trò Chuyện")
    if st.button("🗑️ Xóa Lịch Sử Chat (Sửa đơ/treo)", use_container_width=True):
        st.session_state.messages = []
        st.session_state.recommended_products = []
        st.toast("🧹 Đã làm sạch hội thoại, bạn có thể chat lại bình thường mượt mà!")
        st.rerun()

    st.divider()
    st.markdown("### 🔎 Bộ Lọc Tra Cứu Nhanh")
    CHUYEN_MUC_LIST = ["Tất cả", "Mỹ Phẩm", "Thuốc da liễu", "Thuốc Trị Mụn", "Chăm Sóc Cơ Thể", "Thuốc Trị Sẹo", "Thuốc Da Liễu"]
    if not df_products.empty:
        selected_cat = st.selectbox("Chọn dòng sản phẩm:", CHUYEN_MUC_LIST)
    else:
        selected_cat = "Tất cả"

# 5. THIẾT KẾ KHU VỰC CHÍNH (MAIN CONTENT)
st.markdown("""
    <div style="text-align: center; padding-bottom: 10px;">
        <h1 style="color: #c05c56; font-size: 2.5rem; font-weight: 700; margin-bottom: 0px;">✨ Beauty Haven AI</h1>
        <p style="color: #7c6e6b; font-size: 1.1rem;">Trợ lý phân tích da khoa học & Cửa hàng mỹ phẩm thông minh</p>
    </div>
""", unsafe_allow_html=True)

left_col, right_col = st.columns([3, 2])

# --- PHẦN KHUNG CHAT AI (BÊN TRÁI) ---
with left_col:
    st.subheader("💬 Tư vấn cùng Chuyên gia AI")
    
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
    if prompt := st.chat_input("Hãy mô tả rõ hơn về tình trạng da hiện tại của bạn..."):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        try:
            GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
        except Exception:
            GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            st.error("❌ Chưa cấu hình GEMINI_API_KEY. Tạo file .env với nội dung: GEMINI_API_KEY=your_key")
            st.stop()
        knowledge_base = df_products.to_string(index=False) if not df_products.empty else "Không có dữ liệu."
        
        # Kiểm tra xem câu nói của khách có phải là đồng ý chốt đơn/bỏ giỏ hay không
        # MỚI (Thay thế vào)
# Gọi AI phân tích ý định thay vì dùng từ khóa thủ công
is_agreeing = check_intent_with_ai(client, "gemini-2.5-flash", prompt)
        
# Nếu khách đồng ý VÀ trong bộ nhớ ẩn đang có sẵn sản phẩm đã tư vấn trước đó -> Tự kích hoạt bỏ giỏ luôn không cần qua API
if is_agreeing and st.session_state.recommended_products:
            with st.chat_message("assistant"):
                with st.spinner("Hệ thống đang tự động bốc hàng vào giỏ cho bạn..."):
                    result_msg = add_product_to_cart(st.session_state.recommended_products)
                    answer = f"✨ {result_msg} Em đã chuẩn bị sẵn đơn ở thanh Giỏ hàng bên trái rồi nhé, chị kiểm tra lại xem chính xác chưa nha! 🥰"
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
            st.rerun()
        
elif is_agreeing and not st.session_state.recommended_products:
            # Khách đồng ý nhưng chưa có sản phẩm trong bộ nhớ -> nhắc nhở thay vì tư vấn lại
            with st.chat_message("assistant"):
                answer = "Em chưa xác định được sản phẩm nào để thêm vào giỏ ạ 😊 Chị mô tả tình trạng da hoặc cho em biết muốn lấy sản phẩm nào, em sẽ thêm ngay!"
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            st.rerun()
            
        # Nếu là câu hỏi tư vấn bình thường, gọi API tinh gọn để né lỗi Quota 429
else:
            prompt_he_thong = f"""
            Bạn là chuyên gia tư vấn Skincare chuyên nghiệp. Khách tên {user_name}, {user_age} tuổi, loại da: {user_skin_type}.
            {"Khách chưa biết loại da của mình - hãy hỏi thêm về tình trạng da (bóng dầu, khô, mụn...) để tư vấn phù hợp, hoặc gợi ý sản phẩm phù hợp cho nhiều loại da." if user_skin_type == "Chưa xác định loại da" else ""}
            DANH SÁCH SẢN PHẨM TRONG KHO:
            {knowledge_base}
            
            NHIỆM VỤ:
            1. Tư vấn routine khoa học ngắn gọn bằng sản phẩm có sẵn ở trên. 
            2. Cuối câu hỏi KHÁCH CÓ HÀI LÒNG VÀ MUỐN THÊM CÁC SẢN PHẨM NÀY VÀO GIỎ HÀNG KHÔNG.
            3. Xuất ra một dòng cuối cùng ở định dạng chính xác như sau: [RECOMMEND: tên_sản_phẩm_1, tên_sản_phẩm_2] để hệ thống ghi nhớ.
            """
            
            with st.chat_message("assistant"):
                with st.spinner("AI đang phân tích da..."):
                    try:
                        client = genai.Client(api_key=GEMINI_API_KEY)
                        
                        # Chỉ gửi câu prompt hiện tại để giữ dung lượng siêu nhẹ, tránh lỗi 429 hoàn toàn
                        response = generate_content_with_retries(
                            client=client,
                            model='gemini-2.5-flash',
                            contents=prompt,
                            config=types.GenerateContentConfig(system_instruction=prompt_he_thong, temperature=0.4),
                            max_retries=3
                        )

                        raw_answer = getattr(response, 'text', str(response))
                        
                        # Bóc tách dòng mã hóa [RECOMMEND: ...] ẩn để nạp vào bộ nhớ lưu trữ của Streamlit
                        match_rec = re.search(r'\[RECOMMEND:\s*(.*?)\]', raw_answer)
                        if match_rec:
                            products_extracted = [p.strip() for p in match_rec.group(1).split(',')]
                            st.session_state.recommended_products = products_extracted
                            # Xóa dòng tag thô này đi trước khi hiển thị cho khách nhìn thấy thanh lịch
                            clean_answer = re.sub(r'\[RECOMMEND:\s*(.*?)\]', '', raw_answer).strip()
                        else:
                            clean_answer = raw_answer
                            # KHÔNG reset recommended_products ở đây - giữ nguyên sản phẩm đã tư vấn trước
                            
                        st.markdown(clean_answer)
                        st.session_state.messages.append({"role": "assistant", "content": clean_answer})
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Lỗi kết nối AI: {e}. Vui lòng thử lại hoặc nhấn nút Xóa Lịch Sử Chat ở bên trái!")

# --- PHẦN KỆ TRƯNG BÀY SẢN PHẨM CHỌN MUA (BÊN PHẢI) ---
with right_col:
    st.subheader("🧴 Kệ Sản Phẩm Khuyên Dùng")
    if not df_products.empty:
        chuyen_muc_col = 'Chuyên mục ' if 'Chuyên mục ' in df_products.columns else ('Chuyên mục' if 'Chuyên mục' in df_products.columns else None)
        if chuyen_muc_col and selected_cat != "Tất cả":
            df_filtered = df_products[df_products[chuyen_muc_col].str.strip().str.lower() == selected_cat.strip().lower()]
        else:
            df_filtered = df_products
        if df_filtered.empty: df_filtered = df_products

        for index, row in df_filtered.iterrows():
            p_name = row.get('Tên sản phẩm', f'Mỹ phẩm #{index+1}')
            p_brand = row.get('Xuất xứ ', row.get('Xuất xứ', 'Chính hãng'))
            p_price = row.get('Giá tiền', 'Liên hệ')
            p_effect = row.get('Công dụng', 'Sản phẩm chăm sóc da')
            
            p_image = row.get('Hình ảnh', None) 
            if pd.notna(p_image) and str(p_image).strip() != "" and str(p_image).lower() != "nan":
                p_image = str(p_image).replace('\\', '/').strip()
            else:
                p_image = None
            
            st.markdown(f"""
                <div class="product-card" style="margin-bottom: 0px; border-bottom: none; border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; padding-bottom: 5px;">
                    <span style="background-color: #fecdd3; color: #991b1b; font-size: 0.75rem; font-weight: 600; padding: 3px 8px; border-radius: 20px; display: inline-block; margin-bottom: 8px;">Xuất xứ: {p_brand}</span>
                    <h4 style="margin: 0px; color: #2e2a29; font-size: 1.1rem; font-weight: 600;">{p_name}</h4>
                </div>
            """, unsafe_allow_html=True)
            
            if p_image and os.path.exists(p_image):
                try:
                    st.image(Image.open(p_image), use_container_width=True)
                except:
                    st.caption(f"⚠️ Lỗi định dạng ảnh: {p_image}")
            else:
                st.caption("📸 Chưa có ảnh minh họa")
                
            st.markdown(f"""
                <div class="product-card" style="margin-top: 0px; border-top: none; border-top-left-radius: 0px; border-top-right-radius: 0px; padding-top: 5px;">
                    <p style="font-size: 0.85rem; color: #7c6e6b; margin-top: 5px; margin-bottom: 8px; height: 3.0em; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">✨ {p_effect}</p>
                    <h5 style="color: #c05c56; margin: 0px 0px 10px 0px; font-weight: 700; font-size: 1.2rem;">💰 {p_price}</h5>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"🛒 Thêm vào giỏ hàng", key=f"btn_{p_name}_{index}"):
                st.session_state.cart.append({"name": p_name, "price": p_price})
                st.toast(f"✅ Đã thêm {p_name} vào giỏ hàng!")
                st.rerun()
