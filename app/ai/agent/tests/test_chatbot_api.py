import urllib.request, json
req = urllib.request.Request(
    'http://127.0.0.1:8000/chatbot/agent', 
    data=json.dumps({"question": "what are the activities i can to as admin and user"}).encode(), 
    headers={'Content-Type': 'application/json'}
)
print(urllib.request.urlopen(req).read().decode())
