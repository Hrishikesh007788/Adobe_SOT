import os
from flask import Flask, render_template, request, flash, redirect, send_file, url_for
from flask_bootstrap import Bootstrap
from llama_index import SimpleDirectoryReader, GPTSimpleVectorIndex, LLMPredictor, PromptHelper, ServiceContext
from langchain import OpenAI
import requests
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
import tempfile
import openai
from google.cloud import storage
import glob

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Set your secret key for flash messages

temp_dir = tempfile.TemporaryDirectory()





bootstrap = Bootstrap(app)


os.environ["OPENAI_API_KEY"] = ''
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ''



query = ""  # Variable to store the user's question

GCS_CLIENT = storage.Client()

def upload_cs_file(bucket_name,index_variable_name,destination_file_name):
    bucket = GCS_CLIENT.bucket(bucket_name)
    blob = bucket.blob(destination_file_name)
    blob.upload_from_string(index_variable_name)
    return True




def upload_from_directory(dest_bucket_name: str, directory_path: str, dest_blob_name: str):
    rel_paths = glob.glob(directory_path + '/**', recursive=True)
    bucket = GCS_CLIENT.get_bucket(dest_bucket_name)
    for local_file in rel_paths:
        remote_path = f'{dest_blob_name}/{"/".join(local_file.split(os.sep)[1:])}'
        if os.path.isfile(local_file):
            blob = bucket.blob(remote_path)
            blob.upload_from_filename(local_file)


def list_uploaded_files(bucket_name):
    bucket = GCS_CLIENT.get_bucket(bucket_name)
    blobs = bucket.list_blobs()

    file_names = [blob.name for blob in blobs]
    return file_names


def construct_index_from_gcs_bucket(bucket_name):
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
 
  

    # List files in the GCS bucket
    bucket = GCS_CLIENT.bucket(bucket_name)
    blobs = bucket.list_blobs()

    local_temp_dir = tempfile.mkdtemp()  # Create a temporary local directory
    
    # Download GCS blobs to the local directory
    for blob in blobs:
        filename = os.path.basename(blob.name)
        local_file_path = os.path.join(local_temp_dir, filename)
        blob.download_to_filename(local_file_path)
    
    # Use the local directory for SimpleDirectoryReader
    documents = SimpleDirectoryReader(local_temp_dir).load_data()

 


    service_context = ServiceContext.from_defaults(llm_predictor=llm_predictor, prompt_helper=prompt_helper)
    index = GPTSimpleVectorIndex.from_documents(documents, service_context=service_context)
    
    index_content = index.save_to_string()
   
    upload_cs_file('index_memory_bucket', index_content, 'memory')  

    return index_content




def ask_ai(query):
    index_blob = GCS_CLIENT.get_bucket('index_memory_bucket').blob('memory')
    index_content = index_blob.download_as_text()
    
    index = GPTSimpleVectorIndex.load_from_string(index_content)
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
            
            # Create a Blob object with the appropriate GCS path
            blob_name = f'uploads/{filename}'
            blob = GCS_CLIENT.bucket('all_file_uploads_bucket').blob(blob_name)
            
            # Upload the file directly to the GCS bucket
            blob.upload_from_file(file, content_type=file.content_type)
            
            uploaded_filenames.append(filename)

    return uploaded_filenames




conversation_history = []
conversation_history_user = []
conversation_history_cb = []
    
@app.route('/')
def index():
    global conversation_history

    uploaded_files = list_uploaded_files('all_file_uploads_bucket')

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
            save_text_to_file(extracted_text, "uploads/link_content.txt")

    construct_index_from_gcs_bucket('all_file_uploads_bucket')

  

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

        uploaded_files = list_uploaded_files('all_file_uploads_bucket')

        if not uploaded_files:
            uploaded_files = ["No files uploaded"]

        return render_template('upload.html', answer=response, conversation_history=conversation_history, uploaded_files=uploaded_files)  # Pass uploaded_files to the template
    return redirect(url_for('index'))

@app.route('/download_index', methods=['GET'])
def download_index():
    index_file_path = os.path.join('index.json')
    if os.path.exists(index_file_path):
        try:
            return send_file(index_file_path, as_attachment=True)
        except Exception as e:
            return f"Error occurred while downloading the file: {e}"
    else:
        flash('Please upload a file first.', 'error')
        return redirect(url_for('index'))

    

@app.route('/delete/uploads/<string:filename>', methods=['POST'])
def delete_uploaded_file(filename):
    if request.method == 'POST':
        data = request.get_json()
        if data and 'filename' in data:
            filename = data['filename']
            bucket = GCS_CLIENT.get_bucket('all_file_uploads_bucket')
            blob = bucket.blob(filename)
            blob.delete()
            

            construct_index_from_gcs_bucket('all_file_uploads_bucket')

        return redirect(url_for('index'))


@app.route('/user_ask', methods=['POST', 'GET'])
def user_ask():
    global conversation_history_user, query  # Allow access to the global conversation history and query variables
    uploaded_files = list_uploaded_files('all_file_uploads_bucket')  # Get the list of uploaded files

    if request.method == 'POST':
        user_query = request.form.get('question')
        conversation_history_user.append(("User", user_query))  # Add user's question to the conversation history

        # index_file_path = os.path.join('index.json')
        # if not os.path.exists(index_file_path):
        #     return render_template('chat.html', conversation_history_user=conversation_history_user, alert="No files present. Please upload a file.")

        # Ask the AI and get the response
        response = ask_ai(user_query)
       
        conversation_history_user.append(("AI", response))  # Add AI's response to the conversation history

        if not uploaded_files:
            return render_template('chat.html', answer=response, conversation_history_user=conversation_history_user, alert="No files uploaded. Please upload a file.")

        return render_template('chat.html', answer=response, conversation_history_user=conversation_history_user)  # Pass conversation_history to the template

    return render_template('chat.html', conversation_history_user=conversation_history_user, uploaded_files=uploaded_files)

@app.route('/delete_chat', methods=['POST'])
def delete_chat():
    global conversation_history_user
    conversation_history_user = []  # Clear the conversation history
    return redirect(url_for('user_ask'))




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



@app.template_filter('basename')
def basename_filter(value):
    return os.path.basename(value)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
