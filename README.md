# Amway Cloud Monitor — Telegram

Theo dõi `https://www.amway.com.vn/vn/promotions` bằng GitHub Actions ngay cả khi máy cá nhân và Chrome đang tắt.

## Cách hoạt động

- GitHub Actions chạy mỗi 30 phút (`:17` và `:47`).
- Chrome headless trên máy GitHub mở trang Amway và chờ JavaScript render.
- Chỉ đọc card có tiêu đề `CTKM:`; PDF không được coi là promotion.
- Lần chạy đầu tạo **baseline**, không cảnh báo các chương trình đã tồn tại.
- Khi có promotion mới, workflow gửi Telegram.
- Nếu Telegram gửi lỗi, workflow tạo GitHub Issue dự phòng.
- State lưu trong `data/state.json`; không cần server/database riêng.

## Cài đặt

### 1. Tạo repository GitHub

Tạo **Private repository** tên ví dụ `amway-cloud-monitor`, rồi upload toàn bộ thư mục này vào root repo.

Repo phải có ít nhất:

```text
.github/workflows/monitor.yml
monitor.py
data/state.json
```

### 2. Cho workflow quyền ghi

Vào:

`Settings → Actions → General → Workflow permissions`

chọn:

`Read and write permissions`

rồi **Save**.

### 3. Tạo Telegram Bot

Trong Telegram:

1. Tìm tài khoản **@BotFather**.
2. Gửi `/newbot`.
3. Đặt tên bot và username theo hướng dẫn.
4. BotFather trả về một **Bot Token**. Giữ token này riêng tư.
5. Mở bot vừa tạo và bấm **Start** hoặc gửi một tin nhắn bất kỳ cho bot.

### 4. Lấy Telegram Chat ID

Sau khi đã nhắn cho bot, mở trình duyệt và truy cập:

```text
https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
```

Trong JSON trả về, tìm:

```text
"chat":{"id":123456789,...}
```

Số `123456789` là **Chat ID** của bạn.

### 5. Thêm 2 GitHub Secrets

Trong repo vào:

`Settings → Secrets and variables → Actions → New repository secret`

Tạo:

```text
TELEGRAM_BOT_TOKEN
```

với giá trị token BotFather cấp, và:

```text
TELEGRAM_CHAT_ID
```

với Chat ID ở bước trên.

Không đưa token/chat ID trực tiếp vào code hoặc commit lên repo.

### 6. Chạy baseline lần đầu

Vào:

`Actions → Amway Promotion Monitor → Run workflow`

Lần đầu thành công sẽ có log gần như:

```text
OK: 2 card, NEW=0, baseline=True
```

Không có Telegram ở lần baseline. Từ đó workflow tự chạy mỗi 30 phút.

## Khi có khuyến mãi mới

Telegram nhận tin dạng:

```text
🔔 Amway có 1 chương trình khuyến mãi mới.
https://www.amway.com.vn/vn/promotions
```

Không gửi nội dung chi tiết của promotion, đúng mục tiêu chỉ cần biết có khuyến mãi mới.

## Kiểm tra Telegram ngay sau khi cài

Workflow chỉ gửi khi thật sự có promotion mới, vì vậy để kiểm tra token/chat ID độc lập, có thể dùng URL `getUpdates` ở bước lấy Chat ID để xác nhận bot kết nối đúng. Khi monitor phát hiện promotion mới, Telegram sẽ được dùng tự động.

## Fail-closed

Monitor không cập nhật state khi:

- không thấy heading `CHƯƠNG TRÌNH KHUYẾN MÃI`;
- Amway báo `Failed to load more products`;
- render xong nhưng không đọc được card `CTKM:`;
- Chrome timeout/lỗi.

Một lần website lỗi vì vậy không bị hiểu nhầm thành promotion mới.

## Quota

Workflow chạy 48 lần/ngày. Nếu muốn giảm usage, đổi cron trong `.github/workflows/monitor.yml` thành mỗi giờ:

```yaml
- cron: '17 * * * *'
```
