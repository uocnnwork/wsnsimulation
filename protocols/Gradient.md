# 4. Giao thức Định tuyến Gradient (Gradient Routing Protocol)

[cite_start]Thuật toán Gradient thực hiện các hoạt động khác nhau để duy trì bảng định tuyến[cite: 524]. Các hoạt động này xoay quanh 4 loại gói tin cơ bản và cơ chế quản lý bảng định tuyến cục bộ tại mỗi node.

## 4.1. Các loại gói tin (Message Types)

Thuật toán vận hành dựa trên 4 loại gói tin với các chức năng và phương thức truyền khác nhau:

* [cite_start]**Gradient Beacon:** Đây là gói tin điều khiển nền tảng, chịu trách nhiệm xây dựng và duy trì topology (cấu trúc) mạng[cite: 525]. [cite_start]Gói tin này được truyền theo phương thức Broadcast (Publish) tới tất cả các node lân cận[cite: 526]. [cite_start]Việc Broadcast xảy ra theo chu kỳ hoặc ngay khi node đó vừa cập nhật lại giá trị Gradient của chính mình[cite: 527]. [cite_start]Chức năng của gói tin là thông báo sự tồn tại của node cho các node hàng xóm [cite: 528][cite_start], từ đó cho phép hàng xóm cập nhật Bảng hàng xóm (neighbor table), so sánh Gradient để tìm ra "Best Parent" – tức là node lân cận có gradient thấp nhất và RSSI tốt nhất để chuyển tiếp (forward) gói tin uplink[cite: 529].
* [cite_start]**Uplink Data Message:** Đây là gói tin vận chuyển dữ liệu từ các node cảm biến (Sensor Nodes) hướng về Sink[cite: 530]. [cite_start]Gói tin được truyền theo phương thức Unicast (Hop-by-Hop) hướng về Sink đi qua các Best Parent[cite: 531]. [cite_start]Chức năng chính là chuyển tiếp dữ liệu về Sink; khi gói tin này đi qua node trung gian, node trung gian sẽ trích xuất Source Address (địa chỉ nguồn) và Sender Address (địa chỉ node vừa gửi), sau đó lưu vào bảng reverse routing để biết cách gửi dữ liệu ngược lại cho node nguồn này[cite: 532].
* [cite_start]**Heartbeat Message:** Là một dạng đặc biệt của gói tin Uplink Data, trong đó Payload mang giá trị đặc biệt là `0xFFFF`[cite: 533]. [cite_start]Gói tin này được gửi định kỳ theo máy trạng thái (Fast = 5s / Medium = 10s / Slow = 20s / Maintenance = 30m)[cite: 534]. [cite_start]Tại node nhận, nếu phát hiện payload là `0xFFFF`, node sẽ chỉ cập nhật bảng định tuyến ngược (Reverse Route) mà không chuyển tiếp payload lên tầng ứng dụng để xử lý dữ liệu[cite: 535]. [cite_start]Vai trò của Heartbeat Message là duy trì tính mới của các đường dẫn trong bảng định tuyến ngược, ngăn không cho các entry (mục nhập) bị xóa do cơ chế timeout khi mạng không có lưu lượng dữ liệu liên tục[cite: 536].
* [cite_start]**Backprop Data Message:** Đây là gói tin vận chuyển dữ liệu điều khiển từ Sink xuống một node cảm biến cụ thể, sử dụng cơ chế định tuyến ngược[cite: 537]. [cite_start]Gói tin được truyền theo phương thức Unicast (Hop-by-Hop) dựa trên bảng backprop dest[cite: 538]. [cite_start]Cấu trúc Payload bao gồm Target Address (2 bytes) dùng để các node tra cứu đích đến trong danh sách liên kết backprop node nhằm ra quyết định chuyển tiếp [cite: 539][cite_start], và Data (2 bytes) chứa lệnh điều khiển hoặc dữ liệu cấu hình[cite: 540]. [cite_start]Gói tin này cho phép giao tiếp hai chiều (Bidirectional Communication) mà không cần dùng đến cơ chế Flooding gây nghẽn mạng[cite: 541].

## 4.2. Cấu trúc Bảng Định tuyến Cục bộ

[cite_start]Bảng định tuyến được lưu cục bộ trên mỗi node, chứa nội dung là toàn bộ các hàng xóm lân cận của node đó[cite: 542]. 

[cite_start]**Bảng 1: Ví dụ về nội dung bảng định tuyến cục bộ** [cite: 543]

| Index | Address | Gradient | RSSI(dBm) | last_seen(ms) | backprop_dest |
| :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | `0x0003` | 1 | -55 | 1000 | `0x0005`, `0x0006` |
| 2 | `0x0004` | 1 | -60 | 800 | `0x0007`, `0x0008` |
| 3 | `0x0005` | 2 | -58 | 500 | |
| 4 | `0x0006` | 3 | -60 | 300 | |

*Ý nghĩa các trường trong bảng định tuyến:*
* [cite_start]**Index:** Vị trí của các node trong bảng định tuyến, được sắp xếp bằng cách so sánh lần lượt: giá trị Gradient -> giá trị RSSI -> giá trị last_seen (để chọn đường mới nhất)[cite: 545]. [cite_start]Node ở vị trí Index 1 được gọi là `best_parent`[cite: 546].
* [cite_start]**Address:** Địa chỉ Unicast 16-bit của node lân cận, là định danh duy nhất cho "Next-hop"[cite: 547]. [cite_start]Khi node quyết định chuyển tiếp gói tin, giá trị Address tại Index 1 sẽ được điền vào trường đích (Destination) của gói tin lớp liên kết (Link Layer)[cite: 548].
* [cite_start]**Gradient:** Biểu thị khoảng cách logic từ node địa chỉ tới sink node[cite: 549]. [cite_start]Đây là tham số quan trọng nhất để quyết định chọn đường về sink node[cite: 550].
* [cite_start]**RSSI (dBm):** Chỉ số cường độ tín hiệu thu đo bằng dBm[cite: 551]. [cite_start]Đóng vai trò là tham số phụ để so sánh các node có cùng mức gradient[cite: 552].
* [cite_start]**last_seen(ms):** Dấu thời gian tính bằng mili-giây tại thời điểm cuối cùng nhận được gói tin (Beacon hoặc Data) từ hàng xóm này[cite: 553]. [cite_start]Tham số này dùng để tính giờ cho cơ chế timeout; nếu vượt ngưỡng, liên kết bị coi là đã đứt và entry này sẽ bị xóa khỏi bảng[cite: 554].
* [cite_start]**backprop_dest:** Danh sách chứa địa chỉ của tất cả các node con cháu nằm sâu hơn trong mạng mà có thể tiếp cận được thông qua hàng xóm này[cite: 555]. [cite_start]Đây là trường đặc biệt phục vụ cho chiều xuống (downlink)[cite: 556]. [cite_start]Node chỉ cần biết gửi cho hàng xóm nào để đến đích thay vì lưu bảng định tuyến toàn cục[cite: 557]. [cite_start]Dữ liệu trong danh sách này được xây dựng động thông qua việc học từ các gói tin Uplink[cite: 558].

## 4.3. Cơ chế Hoạt động và Cập nhật Mạng

### 4.3.1. Luồng dữ liệu Uplink (Hướng lên)
* [cite_start]**Trong trạng thái tĩnh:** Đường đi về sink node của các node là cố định; các node định kỳ phát gói tin Beacon mỗi 40s để làm mới trạng thái của mình trong bảng định tuyến của các node lân cận nhằm duy trì kết nối[cite: 574].
* [cite_start]**Khi có sự thay đổi Topology:** Lấy ví dụ khi một node (Node C) ngắt kết nối khỏi mạng[cite: 591].
    * [cite_start]**Tại Node B:** Khi hết thời gian timeout mà không nhận được Beacon từ Node C, Node B xóa Node C khỏi bảng định tuyến[cite: 592]. [cite_start]Ứng viên tốt nhất còn lại (VD: Node A) được chuyển lên Index 1 để làm Best Parent mới[cite: 593].
    * [cite_start]**Tại Node D:** Tương tự, Node D mất Best Parent là Node C[cite: 594]. Node B được đôn lên thay thế. Node D tính toán lại gradient của mình: `Gradient mới của D = Gradient của B + 1`. [cite_start]Sau đó, Node D lập tức broadcast giá trị Gradient mới này ra xung quanh[cite: 595].
    * [cite_start]**Tại Node G:** Khi nhận được Beacon mang gradient mới từ Best Parent của nó là Node D, Node G tự động cập nhật lại Gradient của mình và tiếp tục phát tán bản tin để đồng bộ hóa toàn mạng[cite: 596].

### 4.3.2. Cơ chế hình thành đường đi Downlink (Hướng xuống)
[cite_start]Quy trình xây dựng đường dẫn ngược được thực hiện thông qua việc trích xuất và học dữ liệu từ các gói tin Uplink[cite: 614]. [cite_start]Xét kịch bản Node F gửi dữ liệu qua B, qua C rồi đến Sink: `F -> B -> C -> Sink`[cite: 615].
* [cite_start]**Tại Node B:** Nhận gói tin từ F, trích xuất Sender Address (F) và Source Address (F)[cite: 618]. [cite_start]Địa chỉ nguồn F được lưu vào danh sách `backprop_dest` của hàng xóm F; sau đó gói tin được chuyển tiếp lên Best Parent là C[cite: 619].
* **Tại Node C:** Nhận gói tin từ B, trích xuất Sender Address (B) và Source Address (F). [cite_start]Source Address (F) được lưu vào `backprop_dest` của hàng xóm B; tiếp tục chuyển tiếp lên Sink[cite: 620, 621].
* [cite_start]**Tại Sink Node:** Trích xuất Sender Address (C) và Source Address (F), lưu F vào `backprop_dest` của C và tiến hành giải mã dữ liệu[cite: 622].
* **Kết quả:** Hệ thống tự động học được đường dẫn ngược: Sink biết phải gửi cho C để đến F; C biết phải gửi cho B để đến F; [cite_start]B biết phải gửi trực tiếp cho F[cite: 623].

### 4.3.3. Máy trạng thái Heartbeat
[cite_start]Gói tin Heartbeat được điều khiển bởi một máy trạng thái tự động nhằm cân bằng giữa việc duy trì đường truyền và tiết kiệm năng lượng[cite: 624]. [cite_start]Chu kỳ gửi Heartbeat diễn ra theo 4 trạng thái: Fast State (5s), Medium State (10s), Slow State (20s), và Maintenance State (30m)[cite: 625]. [cite_start]Bất cứ khi nào có "Topology Change Event" (như nút mới tham gia, Best Parent thay đổi, hoặc Gradient bị đổi), máy trạng thái sẽ lập tức quay trở lại Fast State[cite: 626].