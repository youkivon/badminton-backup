# Project README
## Introduction
This project is built using Streamlit, a Python library that allows you to create web apps for data science and machine learning.

## Installation
Before running the application, make sure to install the required dependencies. It is highly recommended to use a virtual environment (venv) to isolate the project dependencies and avoid conflicts with other projects.

To create a virtual environment, run the following command:
```bash
python -m venv venv
```
Then, activate the virtual environment:
```bash
# On Windows
venv\Scripts\activate

# On Linux/Mac
source venv/bin/activate
```
Next, install the required dependencies by running:
```bash
pip install -r requirements.txt
```
Make sure to install all the dependencies listed in the `requirements.txt` file.

## Running the Application
To run the application, navigate to the project root and execute the following command:
```bash
streamlit run frontend/app.py --server.fileWatcherType none
```
This will start the Streamlit server and make the application available in your web browser.

## Notes
* Make sure you have Streamlit installed by running `pip install streamlit` in your terminal.
* The `--server.fileWatcherType none` flag is used to disable file watching, which can improve performance in some cases.