from flask import Flask, request, Response

app = Flask(__name__)

@app.route('/upTransactions', methods=['POST'])
def respond():
    
    return Response(status=200)