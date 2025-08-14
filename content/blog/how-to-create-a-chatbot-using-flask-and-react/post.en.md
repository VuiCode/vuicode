# How to Create a Chatbot Using Flask and React

In this blog post, we will walk through the process of creating a simple chatbot application using Flask for the backend and React for the frontend. By the end of this tutorial, you'll have a fully functional chatbot that can respond to user inputs.

## Clear Result

Before we dive into the code, let’s see what our final product will look like. The chatbot will have a simple interface where users can type their messages and receive responses. Here’s a demo of what we will create:

![Chatbot Demo](https://via.placeholder.com/600x400?text=Chatbot+Demo)

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Setting Up the Flask Backend](#setting-up-the-flask-backend)
3. [Creating the React Frontend](#creating-the-react-frontend)
4. [Connecting Flask and React](#connecting-flask-and-react)
5. [Running the Application](#running-the-application)
6. [Conclusion](#conclusion)

## Prerequisites

Before we start, make sure you have the following installed on your machine:

- Python 3.x
- Node.js and npm
- Flask (`pip install Flask`)
- Flask-CORS (`pip install flask-cors`)

## Setting Up the Flask Backend

1. **Create a new directory for your project**:
   ```bash
   mkdir flask-react-chatbot
   cd flask-react-chatbot
   ```

2. **Create a virtual environment** (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Create a new file named `app.py`** and add the following code:

   ```python
   from flask import Flask, request, jsonify
   from flask_cors import CORS

   app = Flask(__name__)
   CORS(app)

   @app.route('/api/message', methods=['POST'])
   def message():
       user_message = request.json.get('message')
       # Simple response logic
       if "hello" in user_message.lower():
           bot_response = "Hello! How can I help you today?"
       else:
           bot_response = "I'm sorry, I didn't understand that."
       return jsonify({"response": bot_response})

   if __name__ == '__main__':
       app.run(debug=True)
   ```

### Explanation of the Flask Code

- We import necessary libraries and create a Flask app.
- We enable CORS to allow cross-origin requests from our React frontend.
- We define a single route `/api/message` that accepts POST requests. It checks the user's message and returns a simple response based on the input.

## Creating the React Frontend

1. **Create a new React app**:
   ```bash
   npx create-react-app chatbot-frontend
   cd chatbot-frontend
   ```

2. **Install Axios** for making HTTP requests:
   ```bash
   npm install axios
   ```

3. **Open `src/App.js`** and replace the existing code with the following:

   ```javascript
   import React, { useState } from 'react';
   import axios from 'axios';
   import './App.css';

   function App() {
       const [message, setMessage] = useState('');
       const [responses, setResponses] = useState([]);

       const sendMessage = async (e) => {
           e.preventDefault();
           const res = await axios.post('http://localhost:5000/api/message', { message });
           setResponses([...responses, { user: message, bot: res.data.response }]);
           setMessage('');
       };

       return (
           <div className="App">
               <h1>Chatbot</h1>
               <div className="chat-window">
                   {responses.map((resp, index) => (
                       <div key={index}>
                           <p><strong>You:</strong> {resp.user}</p>
                           <p><strong>Bot:</strong> {resp.bot}</p>
                       </div>
                   ))}
               </div>
               <form onSubmit={sendMessage}>
                   <input 
                       type="text" 
                       value={message} 
                       onChange={(e) => setMessage(e.target.value)} 
                       placeholder="Type your message..." 
                       required 
                   />
                   <button type="submit">Send</button>
               </form>
           </div>
       );
   }

   export default App;
   ```

### Explanation of the React Code

- We import React and Axios, and set up state variables for the user input and chatbot responses.
- The `sendMessage` function sends the user message to the Flask backend and updates the response state.
- We render the chat messages and provide an input form for the user to type their messages.

## Connecting Flask and React

1. **Run the Flask backend**:
   ```bash
   python app.py
   ```

2. **Run the React frontend**:
   ```bash
   npm start
   ```

Now, your Flask backend should be running on `http://localhost:5000`, and your React app should be running on `http://localhost:3000`. 

## Running the Application

Open your web browser and navigate to `http://localhost:3000`. You should see the chatbot interface. Try typing "hello" or any other message to see how the bot responds.

## Conclusion

Congratulations! You've successfully created a simple chatbot using Flask for the backend and React for the frontend. This project can be expanded further by adding more complex logic, integrating with machine learning models, or connecting to external APIs to enhance the chatbot's capabilities.

Feel free to experiment with the code and add your own features. Happy coding!