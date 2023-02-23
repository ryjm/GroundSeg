# Flask
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS

# GroundSeg modules
from log import Log

# Create flask app
class GroundSeg:
    def __init__(self, config, orchestrator):
        self.config_object = config
        self.config = config.config
        self.orchestrator = orchestrator

        self.app = Flask(__name__)
        CORS(self.app, supports_credentials=True)


        #
        #   Routes
        #

        # Check if cookie is valid
        @self.app.route("/cookies", methods=['GET'])
        def check_cookies():
            approved, message = self.verify(request)
            if approved:
                return jsonify(200)

            return message

        # List of Urbit Ships in Home Page
        @self.app.route("/urbits", methods=['GET'])
        def all_urbits():
            approved, message = self.verify(request)

            if approved:
                urbs = self.orchestrator.get_urbits()
                return make_response(jsonify(urbs))

            return message

        # Handle urbit ID related requests
        #@self.app.route('/urbit', methods=['GET','POST'])


        # Handle device's system settings
        @self.app.route("/system", methods=['GET','POST'])
        def system_settings():
            approved, message = self.verify(request)

            if approved:
                if request.method == 'GET':
                    return jsonify(self.orchestrator.get_system_settings())

                if request.method == 'POST':
                    module = request.args.get('module')
                    body = request.get_json()
                    sid = request.cookies.get('sessionid')
                    res = self.orchestrator.system_post(module, body, sid)
                    return jsonify(res)

            return message

        # Handle anchor registration related information
        @self.app.route("/anchor", methods=['GET'])
        def anchor_settings():
            approved, message = self.verify(request)

            if approved:
                res = self.orchestrator.get_anchor_settings()
                return jsonify(res)

            return message

        # Bug Reporting
        #@self.app.route("/bug", methods=['POST'])

        
        # Pier upload
        #@self.app.route("/upload", methods=['POST'])


        # Login
        @self.app.route("/login", methods=['POST'])
        def login():
            if self.orchestrator.config['firstBoot']:
                return jsonify('setup')

            return self.orchestrator.handle_login_request(request.get_json())

        # Setup
        @self.app.route("/setup", methods=['POST'])
        def setup():
            if not self.config['firstBoot']:
                return jsonify(400)

            page = request.args.get('page')
            res = self.orchestrator.handle_setup(page, request.get_json())

            return jsonify(res)


    # Check if user is authenticated
    def verify(self, req):
        # User hasn't setup GroundSeg
        if self.config['firstBoot']:
            return (False, jsonify('setup'))

        # Session ID in url arg
        sessionid = req.args.get('sessionid')

        # Session ID as cookie
        if len(str(sessionid)) != 64:
            sessionid = req.cookies.get('sessionid')

        # Verified session
        if sessionid in self.config['sessions']:
            return (True, None)

        # No session ID provided
        return (False, jsonify(404))

    # Run Flask app
    def run(self):
        Log.log("GroundSeg: Starting Flask server")
        debug_mode = self.config_object.debug_mode
        self.app.run(host='0.0.0.0', port=27016, threaded=True, debug=debug_mode, use_reloader=debug_mode)
