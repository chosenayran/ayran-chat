from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ayran_chat_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- BELLEK İÇİ VERİ YAPILARI ---
users = {}          # { 'username': 'password' }
friends = {}        # { 'username': ['friend1', 'friend2'] }
friend_requests = {}# { 'username': ['requester1'] }
servers = []        # [{'id': '...', 'name': '...', 'owner': '...', 'invite_code': '...', 'text_channels': [], 'voice_channels': []}]
dm_rooms = {}       # { 'room_id': ['user1', 'user2'] }

user_sockets = {}   # { 'sid': 'username' }
voice_channels_state = {} # { 'server_id': { 'channel_name': ['user1', 'user2'] } }
active_calls = {}   # { 'target_username': 'caller_username' }


# --- FLASK ROTATALARI ---

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session['username'])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            return render_template('login.html', error="Kullanıcı adı ve şifre gereklidir.")
            
        if username in users and users[username] == password:
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Hatalı kullanıcı adı veya şifre.")
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            return render_template('register.html', error="Kullanıcı adı ve şifre gereklidir.")
            
        if username in users:
            return render_template('register.html', error="Bu kullanıcı adı zaten alınmış.")
            
        users[username] = password
        friends[username] = []
        friend_requests[username] = []
        session['username'] = username
        return redirect(url_for('index'))
        
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


# --- SOCKET.IO OLAYLARI ---

@socketio.on('connect')
def handle_connect():
    username = session.get('username')
    if username:
        user_sockets[request.sid] = username

@socketio.on('disconnect')
def handle_disconnect():
    username = user_sockets.pop(request.sid, None)
    if username:
        for s_id in voice_channels_state:
            for chan in voice_channels_state[s_id]:
                if username in voice_channels_state[s_id][chan]:
                    voice_channels_state[s_id][chan].remove(username)
        emit('update_all_voice_members', voice_channels_state, broadcast=True)

# --- SUNUCU YÖNETİMİ ---

@socketio.on('get_servers')
def handle_get_servers():
    emit('load_servers', servers)

@socketio.on('create_server')
def handle_create_server(data):
    username = session.get('username')
    server_name = data.get('name')
    if username and server_name:
        server_id = str(uuid.uuid4())[:8]
        invite_code = server_name.upper().replace(' ', '') + "-" + str(uuid.uuid4())[:4].upper()
        
        new_server = {
            'id': server_id,
            'name': server_name,
            'owner': username,
            'invite_code': invite_code,
            'text_channels': ['genel'],
            'voice_channels': ['Genel Ses']
        }
        servers.append(new_server)
        voice_channels_state[server_id] = {'Genel Ses': []}
        emit('load_servers', servers, broadcast=True)

@socketio.on('join_by_invite')
def handle_join_by_invite(data):
    code = data.get('code', '').strip()
    found = False
    for srv in servers:
        if srv['invite_code'] == code:
            found = True
            break
    if found:
        emit('join_invite_response', {'success': True, 'message': 'Sunucuya katıldınız!'})
        emit('load_servers', servers)
    else:
        emit('join_invite_response', {'success': False, 'message': 'Geçersiz davet kodu.'})

@socketio.on('get_invite_code')
def handle_get_invite_code(data):
    server_id = data.get('server_id')
    for srv in servers:
        if srv['id'] == server_id:
            emit('show_invite_code', {'server_name': srv['name'], 'code': srv['invite_code']})
            break

@socketio.on('create_channel')
def handle_create_channel(data):
    server_id = data.get('server_id')
    channel_name = data.get('channel_name')
    c_type = data.get('type')
    
    for srv in servers:
        if srv['id'] == server_id:
            if c_type == 'text' and channel_name not in srv['text_channels']:
                srv['text_channels'].append(channel_name)
            elif c_type == 'voice' and channel_name not in srv['voice_channels']:
                srv['voice_channels'].append(channel_name)
                if server_id not in voice_channels_state:
                    voice_channels_state[server_id] = {}
                voice_channels_state[server_id][channel_name] = []
            break
    emit('load_servers', servers, broadcast=True)


# --- MESAJLAŞMA VE ODALAR ---

@socketio.on('join_channel')
def handle_join_channel(data):
    room = f"{data['server_id']}_{data['channel']}"
    join_room(room)

@socketio.on('leave_channel')
def handle_leave_channel(data):
    room = f"{data['server_id']}_{data['channel']}"
    leave_room(room)

@socketio.on('send_message')
def handle_send_message(data):
    username = session.get('username')
    room = f"{data['server_id']}_{data['channel']}"
    emit('receive_message', {'user': username, 'message': data['message']}, room=room)

@socketio.on('join_dm')
def handle_join_dm(data):
    username = session.get('username')
    target = data.get('target')
    room_name = "_".join(sorted([username, target]))
    join_room(room_name)

@socketio.on('send_dm_message')
def handle_send_dm(data):
    username = session.get('username')
    target = data.get('target')
    room_name = "_".join(sorted([username, target]))
    emit('receive_message', {'user': username, 'message': data['message']}, room=room_name)


# --- ARKADAŞLIK SİSTEMİ ---

@socketio.on('get_friend_data')
def handle_get_friend_data():
    username = session.get('username')
    if username:
        emit('update_friend_data', {
            'friends': friends.get(username, []),
            'requests': friend_requests.get(username, [])
        })

@socketio.on('send_friend_request')
def handle_send_friend_request(data):
    username = session.get('username')
    target = data.get('target')
    
    if target not in users:
        emit('friend_response', {'message': 'Kullanıcı bulunamadı.'})
        return
    if target == username:
        emit('friend_response', {'message': 'Kendinize istek gönderemezsiniz.'})
        return
    if target in friends.get(username, []):
        emit('friend_response', {'message': 'Bu kullanıcı zaten arkadaşınız.'})
        return
        
    if username not in friend_requests[target]:
        friend_requests[target].append(username)
        emit('friend_response', {'message': 'Arkadaşlık isteği gönderildi!'})
        
        for sid, usr in user_sockets.items():
            if usr == target:
                emit('update_friend_data', {
                    'friends': friends.get(target, []),
                    'requests': friend_requests.get(target, [])
                }, room=sid)

@socketio.on('accept_friend_request')
def handle_accept_friend_request(data):
    username = session.get('username')
    requester = data.get('requester')
    
    if requester in friend_requests.get(username, []):
        friend_requests[username].remove(requester)
        friends[username].append(requester)
        friends[requester].append(username)
        
        emit('update_friend_data', {
            'friends': friends.get(username, []),
            'requests': friend_requests.get(username, [])
        })
        
        for sid, usr in user_sockets.items():
            if usr == requester:
                emit('update_friend_data', {
                    'friends': friends.get(requester, []),
                    'requests': friend_requests.get(requester, [])
                }, room=sid)


# --- SES VE ARAMA MANTIĞI (WEBRTC SİNYALLEŞME) ---

@socketio.on('join_voice')
def handle_join_voice(data):
    username = session.get('username')
    server_id = data.get('server_id')
    channel = data.get('channel')
    
    if server_id not in voice_channels_state:
        voice_channels_state[server_id] = {}
    if channel not in voice_channels_state[server_id]:
        voice_channels_state[server_id][channel] = []
        
    if username not in voice_channels_state[server_id][channel]:
        voice_channels_state[server_id][channel].append(username)
        
    room = f"voice_{server_id}_{channel}"
    join_room(room)
    
    emit('user_joined_voice_signal', {'sid': request.sid, 'user': username}, room=room, include_self=False)
    emit('update_all_voice_members', voice_channels_state, broadcast=True)

@socketio.on('leave_voice')
def handle_leave_voice(data):
    username = session.get('username')
    server_id = data.get('server_id')
    channel = data.get('channel')
    
    if server_id in voice_channels_state and channel in voice_channels_state[server_id]:
        if username in voice_channels_state[server_id][channel]:
            voice_channels_state[server_id][channel].remove(username)
            
    room = f"voice_{server_id}_{channel}"
    leave_room(room)
    emit('update_all_voice_members', voice_channels_state, broadcast=True)

@socketio.on('start_call')
def handle_start_call(data):
    target_user = data.get('target')
    caller_user = session.get('username')
    
    if target_user and caller_user:
        active_calls[target_user] = caller_user

    for sid, user in user_sockets.items():
        if user == target_user:
            emit('incoming_call', {'from': caller_user, 'sid': request.sid}, room=sid)
            break

@socketio.on('reject_call')
def handle_reject_call(data):
    rejector_user = session.get('username')
    
    caller_user = active_calls.pop(rejector_user, None)
    if not caller_user:
        caller_user = data.get('target')

    if caller_user:
        for sid, user in user_sockets.items():
            if user == caller_user:
                emit('call_rejected', room=sid)
                break

@socketio.on('signal')
def handle_signal(data):
    target_sid = data.get('to')
    emit('signal', {'sid': request.sid, 'sdp': data.get('sdp'), 'ice': data.get('ice')}, room=target_sid)


if __name__ == '__main__':
    socketio.run(app, debug=True)