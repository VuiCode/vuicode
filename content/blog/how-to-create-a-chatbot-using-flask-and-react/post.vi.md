# Tạo Chatbot Đơn Giản Sử Dụng Flask và React

## Kết quả rõ ràng
Trong bài viết này, bạn sẽ học cách tạo một chatbot đơn giản sử dụng Flask cho phần backend và React cho phần frontend. Sau khi hoàn thành, bạn sẽ có một ứng dụng chatbot có thể nhận và phản hồi tin nhắn từ người dùng.

## Giới thiệu
Chatbot là một ứng dụng thú vị và hữu ích, có thể giúp tự động hóa nhiều nhiệm vụ. Trong bài viết này, chúng ta sẽ xây dựng một chatbot cơ bản sử dụng Flask làm API backend và React làm frontend. Chúng ta sẽ không đi sâu vào các kỹ thuật phức tạp, mà sẽ tập trung vào cách làm đơn giản nhất để ai cũng có thể thực hiện.

## Chuẩn bị môi trường
Trước khi bắt đầu, hãy đảm bảo bạn đã cài đặt các công cụ cần thiết:
- Python (phiên bản 3.6 trở lên)
- Node.js và npm
- Flask và Flask-CORS
- Create React App

### Cài đặt Flask
Đầu tiên, bạn cần cài đặt Flask và Flask-CORS. Mở terminal và chạy lệnh sau:

```bash
pip install Flask Flask-CORS
```

### Tạo cấu trúc thư mục
Tạo một thư mục cho dự án của bạn và bên trong đó, tạo hai thư mục con: `backend` và `frontend`.

```bash
mkdir chatbot
cd chatbot
mkdir backend frontend
```

## Tạo Flask API
Bây giờ, chúng ta sẽ tạo một API đơn giản bằng Flask. Tạo file `app.py` trong thư mục `backend` và thêm mã sau:

```python
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    bot_response = f"Bot: Bạn đã nói: {user_message}"
    return jsonify({"response": bot_response})

if __name__ == '__main__':
    app.run(debug=True)
```

### Giải thích mã
- Chúng ta import Flask và CORS để xử lý các yêu cầu từ frontend.
- Tạo một route `/chat` để nhận tin nhắn từ người dùng và trả về phản hồi.
- Phản hồi của bot là một chuỗi đơn giản, bạn có thể thay đổi nó để tạo ra phản hồi phức tạp hơn.

## Tạo React Frontend
Tiếp theo, chúng ta sẽ tạo một ứng dụng React. Trong thư mục `frontend`, chạy lệnh sau để tạo một ứng dụng React mới:

```bash
npx create-react-app .
```

### Cài đặt Axios
Chúng ta sẽ sử dụng Axios để gửi yêu cầu đến API Flask. Cài đặt Axios bằng lệnh:

```bash
npm install axios
```

### Tạo giao diện người dùng
Mở file `src/App.js` và thay thế nội dung bằng mã sau:

```javascript
import React, { useState } from 'react';
import axios from 'axios';

function App() {
  const [message, setMessage] = useState('');
  const [responses, setResponses] = useState([]);

  const sendMessage = async () => {
    const res = await axios.post('http://127.0.0.1:5000/chat', { message });
    setResponses([...responses, res.data.response]);
    setMessage('');
  };

  return (
    <div style={{ padding: '20px' }}>
      <h1>Chatbot</h1>
      <div>
        {responses.map((response, index) => (
          <div key={index}>{response}</div>
        ))}
      </div>
      <input
        type="text"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="Nhập tin nhắn..."
      />
      <button onClick={sendMessage}>Gửi</button>
    </div>
  );
}

export default App;
```

### Giải thích mã
- Chúng ta sử dụng `useState` để quản lý trạng thái của tin nhắn và phản hồi.
- Hàm `sendMessage` sẽ gửi tin nhắn đến API Flask và nhận phản hồi.
- Giao diện đơn giản với một ô nhập liệu và nút gửi.

## Chạy ứng dụng
### Bước 1: Chạy Flask API
Mở terminal trong thư mục `backend` và chạy lệnh:

```bash
python app.py
```

### Bước 2: Chạy React App
Mở terminal khác trong thư mục `frontend` và chạy lệnh:

```bash
npm start
```

Truy cập vào `http://localhost:3000` trong trình duyệt của bạn. Bạn sẽ thấy giao diện chatbot đơn giản. Nhập một tin nhắn và nhấn nút gửi, bạn sẽ thấy phản hồi từ bot.

## Kết luận
Chúng ta đã tạo một chatbot đơn giản sử dụng Flask và React. Đây là một dự án cơ bản nhưng rất hữu ích để bạn hiểu cách kết nối frontend và backend. Bạn có thể mở rộng chatbot này bằng cách thêm các tính năng như xử lý ngôn ngữ tự nhiên, lưu trữ lịch sử trò chuyện, hoặc tích hợp với các dịch vụ bên ngoài.

Chúc bạn thành công với dự án chatbot của mình!