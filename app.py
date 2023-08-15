import os
import shutil
from flask import Flask, jsonify, render_template, request, flash, redirect, send_file, url_for
from flask_bootstrap import Bootstrap
from llama_index import SimpleDirectoryReader, GPTListIndex, readers, GPTSimpleVectorIndex, LLMPredictor, PromptHelper, ServiceContext
from langchain import OpenAI
import sys
import os
import requests
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
import tempfile
import openai

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Set your secret key for flash messages

temp_dir = tempfile.TemporaryDirectory()
app.config['UPLOAD_FOLDER'] = temp_dir.name

index_temp_dir = tempfile.TemporaryDirectory()
index_temp_path = index_temp_dir.name


bootstrap = Bootstrap(app)


os.environ["OPENAI_API_KEY"] = ''


query = ""  # Variable to store the user's question

def construct_index(directory_path):

    openai.api_key = ""
    # set maximum input size
    max_input_size = 4096
    # set number of output tokens
    num_outputs = 2000
    # set maximum chunk overlap
    max_chunk_overlap = 20
    # set chunk size limit
    chunk_size_limit = 600 

    # define prompt helper
    prompt_helper = PromptHelper(max_input_size, num_outputs, max_chunk_overlap, chunk_size_limit=chunk_size_limit)

    # define LLM
    llm_predictor = LLMPredictor(llm=OpenAI(temperature=0.5, model_name="text-davinci-003", max_tokens=num_outputs))
 
    documents = SimpleDirectoryReader(directory_path).load_data()
    
    service_context = ServiceContext.from_defaults(llm_predictor=llm_predictor, prompt_helper=prompt_helper)
    index = GPTSimpleVectorIndex.from_documents(documents, service_context=service_context)

    # index.save_to_disk('index.json')

    with tempfile.TemporaryDirectory() as temp_dir:
        index.save_to_disk(os.path.join(index_temp_path, 'index.json'))

              # index.json in temp path
        print(os.path.join(index_temp_path, 'index.json'))

        # After saving, copy the index.json to your app's upload folder
        # index_json_path = os.path.join(temp_dir, 'index.json')    
        # shutil.copy(index_json_path, app.config['UPLOAD_FOLDER'])



       

    return index



def ask_ai(query):
    index = GPTSimpleVectorIndex.load_from_disk(os.path.join(index_temp_path, 'index.json'))
    response = index.query(query)
    return response



def extract_text_from_webpage(url):
    try:
        # Send a GET request to the URL
        response = requests.get(url)
        response.raise_for_status()  # Check if the request was successful

        # Parse the HTML content using BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract all the text from the HTML
        text = soup.get_text()

        return text
    except requests.exceptions.RequestException as e:
        print(f"Error occurred: {e}")
        return None
    
def save_text_to_file(text, filename):
    try:
        with open(filename, 'a', encoding='utf-8') as file:  
            file.write(text)
        print(f"Text has been appended to {filename}")
    except Exception as e:
        print(f"Error occurred while saving the file: {e}")


def upload_files(request_files):
    uploaded_filenames = []
    for file in request_files.getlist('file'):
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            uploaded_filenames.append(filename)
    return uploaded_filenames



conversation_history = []
conversation_history_user = []
conversation_history_cb = []
    
@app.route('/')
def index():

     # Temp path
    print(temp_dir.name)

    

        
        # Uploads in temp path
    print(['UPLOAD_FOLDER'])  

    global conversation_history  # Allow access to the global conversation history variable

    uploaded_files = os.listdir(app.config['UPLOAD_FOLDER'])  # Get the list of uploaded files

    if not uploaded_files:
        uploaded_files = ["No files uploaded"]

    return render_template('upload.html', conversation_history=conversation_history, uploaded_files=uploaded_files)

@app.route('/upload', methods=['POST'])
def upload_file():
    global query  # Allow access to the global query variable
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)

        uploaded_filenames = upload_files(request.files)

    if not uploaded_filenames and 'link' not in request.form:
        flash('No selected file or link', 'error')
        return redirect(request.url)

    link = request.form.get('link', '')
    if link:
        extracted_text = extract_text_from_webpage(link)
        flash(f'Link uploaded successfully!', 'success')
        if extracted_text:
            save_text_to_file(extracted_text, os.path.join(temp_dir.name, "link_content.txt"))

    construct_index(temp_dir.name)  # Use the temporary directory

    return redirect(url_for('index'))


@app.route('/admin_ask', methods=['POST'])
def ask_question():
    global query, conversation_history  # Allow access to the global query and conversation history variables
    if request.method == 'POST':
        query = request.form.get('question')
        conversation_history.append(("User", query))  # Add user's question to the conversation history

        # Ask the AI and get the response
        response = ask_ai(query)
        conversation_history.append(("AI", response))  # Add AI's response to the conversation history

        uploaded_files = os.listdir(app.config['UPLOAD_FOLDER'])  # Get the list of uploaded files

        if not uploaded_files:
            uploaded_files = ["No files uploaded"]

        return render_template('upload.html', answer=response, conversation_history=conversation_history, uploaded_files=uploaded_files)  # Pass uploaded_files to the template
    return redirect(url_for('index'))

@app.route('/download_index', methods=['GET'])
def download_index():
    index_file_path = os.path.join(index_temp_path, 'index.json')
    if os.path.exists(index_file_path):
        try:
            return send_file(index_file_path, as_attachment=True)
        except Exception as e:
            return f"Error occurred while downloading the file: {e}"
    else:
        flash('Please upload a file first.', 'error')
        return redirect(url_for('index'))



# def delete_file(filename):
#     try:
#         os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filename))
#         return "File deleted successfully!"
#     except Exception as e:
#         return f"Error occurred while deleting the file: {e}"

# @app.route('/delete/<string:filename>', methods=['GET'])
# def delete_uploaded_file(filename):
#     file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#     if os.path.exists(file_path):
#         try:
#             os.remove(file_path)
#             construct_index(temp_dir.name)  # Call construct_index function after file deletion
#             return "File deleted successfully!"
#         except Exception as e:
#             return f"Error occurred while deleting the file: {e}"
#     else:
#         return "File not found."
    

@app.route('/delete/<string:filename>', methods=['POST'])
def delete_uploaded_file(filename):
    if request.method == 'POST':
        data = request.get_json()
        if data and 'filename' in data:
            filename = data['filename']
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            # Rest of the code remains the same
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    construct_index(temp_dir.name)  # Call construct_index function after file deletion
                    return "File deleted successfully!"
                except Exception as e:
                    return f"Error occurred while deleting the file: {e}"
            else:
                return "File not found."
            
        return redirect(url_for('index'))


@app.route('/user_ask', methods=['POST', 'GET'])
def user_ask():
    global conversation_history_user, query  # Allow access to the global conversation history and query variables
    if request.method == 'POST':
        user_query = request.form.get('question')
        conversation_history_user.append(("User", user_query))  # Add user's question to the conversation history

        # Ask the AI and get the response
        response = ask_ai(user_query)
        conversation_history_user.append(("AI", response))  # Add AI's response to the conversation history

        uploaded_files = os.listdir(app.config['UPLOAD_FOLDER'])  # Get the list of uploaded files

        if not uploaded_files:
            uploaded_files = ["No files uploaded"]

        return render_template('chat.html', answer=response, conversation_history_user=conversation_history_user)  # Pass conversation_history to the template
    return render_template('chat.html', conversation_history_user=conversation_history_user)



@app.route('/chatbot', methods=['GET', 'POST'])


def chat():

    

    global conversation_history_cb

    if request.method == 'POST':
        user_input = request.form['user_input']

        # Append user input to conversation history
        conversation_history_cb.append(("You", user_input))

        # Get chatbot's response
        response = ask_ai(user_input)

        # Append chatbot's response to conversation history
        conversation_history_cb.append(("Chatbot", response))
        



        return render_template('chatbot.html', conversation_history_cb=conversation_history_cb)
    else:
        response = "Hello! I'm Chatbot. How can I help you?"
        return render_template('chatbot.html', conversation_history_cb=conversation_history_cb, response=response)
    

def allowed_file(filename):
    allowed_extensions = ['txt', 'pdf', 'docx' , 'pptx' , 'json']
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
