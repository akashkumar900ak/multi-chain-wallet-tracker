import os
import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from web3 import Web3
import requests
from dataclasses import dataclass
from typing import Dict, List, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8031337051:AAHNNUgJ9wWUgwQdKEH4Preg3kS4HeV6ug4')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '1114236546')
ALCHEMY_API_KEY = os.environ.get('ALCHEMY_API_KEY', '')

# Free RPC endpoints (no API key required)
CHAINS = {
    'ethereum': {
        'name': 'Ethereum',
        'rpc_url': 'https://eth.llamarpc.com',
        'explorer': 'https://etherscan.io',
        'chain_id': 1
    },
    'polygon': {
        'name': 'Polygon',
        'rpc_url': 'https://polygon-rpc.com',
        'explorer': 'https://polygonscan.com',
        'chain_id': 137
    },
    'bsc': {
        'name': 'BNB Chain',
        'rpc_url': 'https://bsc-dataseed.binance.org/',
        'explorer': 'https://bscscan.com',
        'chain_id': 56
    }
}

@dataclass
class WalletInfo:
    address: str
    chain: str
    label: str
    last_checked: datetime
    last_tx_hash: Optional[str] = None

# In-memory storage (replace with database in production)
tracked_wallets: List[WalletInfo] = []
recent_transactions: List[Dict] = []
templates_created = False

class MultiChainWalletTracker:
    def __init__(self):
        self.web3_connections = {}
        self.initialize_connections()
    
    def initialize_connections(self):
        """Initialize Web3 connections for each chain"""
        for chain_id, config in CHAINS.items():
            try:
                w3 = Web3(Web3.HTTPProvider(config['rpc_url']))
                if w3.is_connected():
                    self.web3_connections[chain_id] = w3
                    logger.info(f"Connected to {config['name']}")
                else:
                    logger.error(f"Failed to connect to {config['name']}")
            except Exception as e:
                logger.error(f"Error connecting to {config['name']}: {e}")
    
    def get_wallet_balance(self, address: str, chain: str) -> Optional[str]:
        """Get wallet balance"""
        try:
            if chain not in self.web3_connections:
                return None
            
            w3 = self.web3_connections[chain]
            balance_wei = w3.eth.get_balance(address)
            balance_eth = w3.from_wei(balance_wei, 'ether')
            return f"{balance_eth:.6f}"
        except Exception as e:
            logger.error(f"Error getting balance for {address} on {chain}: {e}")
            return None
    
    def get_transaction_count(self, address: str, chain: str) -> Optional[int]:
        """Get transaction count for address"""
        try:
            if chain not in self.web3_connections:
                return None
            
            w3 = self.web3_connections[chain]
            return w3.eth.get_transaction_count(address)
        except Exception as e:
            logger.error(f"Error getting transaction count for {address} on {chain}: {e}")
            return None
    
    def send_telegram_alert(self, message: str):
        """Send alert to Telegram"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram credentials not configured")
            return
        
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram alert sent successfully")
            else:
                logger.error(f"Failed to send Telegram alert: {response.text}")
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
    
    def monitor_wallet(self, wallet: WalletInfo):
        """Monitor a single wallet for changes"""
        try:
            # Get current transaction count
            current_tx_count = self.get_transaction_count(wallet.address, wallet.chain)
            
            if current_tx_count is not None:
                # Check if transaction count changed (new transaction)
                if wallet.last_tx_hash is None:
                    wallet.last_tx_hash = str(current_tx_count)
                elif str(current_tx_count) != wallet.last_tx_hash:
                    # New transaction detected
                    wallet.last_tx_hash = str(current_tx_count)
                    
                    # Get current balance
                    balance = self.get_wallet_balance(wallet.address, wallet.chain)
                    
                    # Add to recent transactions
                    recent_transactions.append({
                        'wallet_label': wallet.label,
                        'address': wallet.address,
                        'chain': wallet.chain,
                        'tx_count': current_tx_count,
                        'balance': balance,
                        'timestamp': datetime.now(),
                        'explorer_url': f"{CHAINS[wallet.chain]['explorer']}/address/{wallet.address}"
                    })
                    
                    # Keep only last 50 transactions
                    if len(recent_transactions) > 50:
                        recent_transactions.pop(0)
                    
                    # Send Telegram alert
                    chain_name = CHAINS[wallet.chain]['name']
                    message = f"""
🔔 <b>Wallet Activity Alert</b>

💼 Wallet: {wallet.label}
🌐 Chain: {chain_name}
📍 Address: {wallet.address[:10]}...{wallet.address[-10:]}
📊 Total Transactions: {current_tx_count}
💰 Current Balance: {balance} ETH
🔗 <a href="{CHAINS[wallet.chain]['explorer']}/address/{wallet.address}">View on Explorer</a>
"""
                    self.send_telegram_alert(message)
                    logger.info(f"Activity detected for {wallet.label}")
            
            wallet.last_checked = datetime.now()
            
        except Exception as e:
            logger.error(f"Error monitoring wallet {wallet.address}: {e}")

# Initialize tracker
tracker = MultiChainWalletTracker()

def background_monitor():
    """Background monitoring function"""
    while True:
        try:
            for wallet in tracked_wallets:
                tracker.monitor_wallet(wallet)
                time.sleep(5)  # Small delay between wallets
            time.sleep(30)  # Check every 30 seconds
        except Exception as e:
            logger.error(f"Error in background monitor: {e}")
            time.sleep(60)  # Wait longer on error

# Start background monitoring
monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

def create_templates():
    """Create templates directory and basic HTML template"""
    global templates_created
    if templates_created:
        return
    
    try:
        # Create templates directory
        templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
        os.makedirs(templates_dir, exist_ok=True)
        
        # Create basic HTML template
        html_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Chain Wallet Tracker</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .fade-in { animation: fadeIn 0.5s ease-in; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-4xl font-bold text-center mb-8 text-gray-800">🔍 Multi-Chain Wallet Tracker</h1>
        
        <!-- Status Bar -->
        <div class="bg-white rounded-lg shadow-md p-4 mb-6">
            <div class="flex justify-between items-center">
                <div class="text-sm text-gray-600">
                    Connected Chains: 
                    {% for chain_id, chain in chains.items() %}
                        <span class="inline-block bg-green-100 text-green-800 px-2 py-1 rounded-full text-xs mr-2">{{ chain.name }}</span>
                    {% endfor %}
                </div>
                <div class="text-sm text-gray-600">
                    Last Updated: <span id="lastUpdate">{{ moment().format('HH:mm:ss') }}</span>
                </div>
            </div>
        </div>
        
        <!-- Add Wallet Form -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-2xl font-semibold mb-4">➕ Add New Wallet</h2>
            <form id="addWalletForm" class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <input type="text" id="address" placeholder="Wallet Address (0x...)" class="px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" required>
                <select id="chain" class="px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" required>
                    <option value="">Select Chain</option>
                    <option value="ethereum">Ethereum</option>
                    <option value="polygon">Polygon</option>
                    <option value="bsc">BNB Chain</option>
                </select>
                <input type="text" id="label" placeholder="Wallet Label" class="px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" required>
                <button type="submit" class="bg-blue-500 text-white px-6 py-2 rounded-lg hover:bg-blue-600 transition-colors">Add Wallet</button>
            </form>
        </div>
        
        <!-- Tracked Wallets -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-2xl font-semibold mb-4">👁️ Tracked Wallets ({{ wallets|length }})</h2>
            <div id="walletsList" class="space-y-4">
                {% for wallet in wallets %}
                <div class="border rounded-lg p-4 bg-gray-50 hover:bg-gray-100 transition-colors">
                    <div class="flex justify-between items-center">
                        <div class="flex-1">
                            <h3 class="font-semibold text-lg">{{ wallet.label }}</h3>
                            <p class="text-gray-600 text-sm font-mono">{{ wallet.address }}</p>
                            <div class="flex items-center space-x-4 mt-2">
                                <span class="text-gray-500 text-xs">{{ chains[wallet.chain]['name'] }}</span>
                                <span class="text-gray-500 text-xs">Last checked: {{ wallet.last_checked.strftime('%H:%M:%S') }}</span>
                                {% if wallet.last_tx_hash %}
                                <span class="text-green-600 text-xs">✓ Active</span>
                                {% endif %}
                            </div>
                        </div>
                        <div class="flex space-x-2">
                            <a href="{{ chains[wallet.chain]['explorer'] }}/address/{{ wallet.address }}" target="_blank" class="bg-green-500 text-white px-3 py-1 rounded text-sm hover:bg-green-600 transition-colors">View</a>
                            <button onclick="removeWallet('{{ wallet.address }}', '{{ wallet.chain }}')" class="bg-red-500 text-white px-3 py-1 rounded text-sm hover:bg-red-600 transition-colors">Remove</button>
                        </div>
                    </div>
                </div>
                {% endfor %}
                {% if not wallets %}
                <div class="text-center py-12">
                    <p class="text-gray-500 text-lg">No wallets being tracked yet</p>
                    <p class="text-gray-400 text-sm">Add your first wallet above to get started!</p>
                </div>
                {% endif %}
            </div>
        </div>
        
        <!-- Recent Activity -->
        <div class="bg-white rounded-lg shadow-md p-6">
            <h2 class="text-2xl font-semibold mb-4">📊 Recent Activity</h2>
            <div class="space-y-4">
                {% for tx in recent_transactions %}
                <div class="border-l-4 border-blue-500 pl-4 py-3 bg-blue-50 rounded-r-lg">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <h4 class="font-semibold text-lg">{{ tx.wallet_label }}</h4>
                            <p class="text-sm text-gray-600 capitalize">{{ chains[tx.chain]['name'] }} Network</p>
                            <div class="flex items-center space-x-4 mt-1">
                                <span class="text-xs text-gray-500">{{ tx.timestamp.strftime('%Y-%m-%d %H:%M:%S') if tx.timestamp else 'N/A' }}</span>
                                <span class="text-xs text-gray-500">Transactions: {{ tx.tx_count }}</span>
                                {% if tx.balance %}
                                <span class="text-xs text-gray-500">Balance: {{ tx.balance }} ETH</span>
                                {% endif %}
                            </div>
                        </div>
                        <a href="{{ tx.explorer_url }}" target="_blank" class="text-blue-500 hover:text-blue-700 text-sm font-medium">View Explorer →</a>
                    </div>
                </div>
                {% endfor %}
                {% if not recent_transactions %}
                <div class="text-center py-8">
                    <p class="text-gray-500">No activity detected yet</p>
                    <p class="text-gray-400 text-sm">Activity will appear here when wallets have new transactions</p>
                </div>
                {% endif %}
            </div>
        </div>
        
        <!-- Footer -->
        <div class="text-center mt-8 text-gray-500 text-sm">
            <p>Multi-Chain Wallet Tracker • Monitoring Ethereum, Polygon & BNB Chain</p>
        </div>
    </div>
    
    <script>
        // Add wallet form handler
        document.getElementById('addWalletForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const submitBtn = e.target.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = 'Adding...';
            submitBtn.disabled = true;
            
            const formData = new FormData();
            formData.append('address', document.getElementById('address').value);
            formData.append('chain', document.getElementById('chain').value);
            formData.append('label', document.getElementById('label').value);
            
            try {
                const response = await fetch('/add_wallet', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ Wallet added successfully!');
                    location.reload();
                } else {
                    alert('❌ Error: ' + result.error);
                }
            } catch (error) {
                alert('❌ Error adding wallet: ' + error.message);
            } finally {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }
        });
        
        // Remove wallet function
        async function removeWallet(address, chain) {
            if (!confirm('Are you sure you want to remove this wallet from tracking?')) return;
            
            try {
                const response = await fetch('/remove_wallet', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ address, chain })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert('✅ Wallet removed successfully!');
                    location.reload();
                } else {
                    alert('❌ Error: ' + result.error);
                }
            } catch (error) {
                alert('❌ Error removing wallet: ' + error.message);
            }
        }
        
        // Update last update time
        function updateTime() {
            const now = new Date();
            document.getElementById('lastUpdate').textContent = now.toLocaleTimeString();
        }
        
        // Auto-refresh every 60 seconds
        setInterval(() => {
            location.reload();
        }, 60000);
        
        // Update time every second
        setInterval(updateTime, 1000);
    </script>
</body>
</html>'''
        
        # Write template file
        template_path = os.path.join(templates_dir, 'index.html')
        with open(template_path, 'w') as f:
            f.write(html_template)
        
        templates_created = True
        logger.info("Templates created successfully")
        
    except Exception as e:
        logger.error(f"Error creating templates: {e}")

# Routes
@app.route('/')
def index():
    """Main dashboard"""
    # Ensure templates are created
    create_templates()
    
    return render_template('index.html', 
                         wallets=tracked_wallets, 
                         chains=CHAINS,
                         recent_transactions=recent_transactions[-10:])  # Show last 10 transactions

@app.route('/add_wallet', methods=['POST'])
def add_wallet():
    """Add a new wallet to track"""
    try:
        address = request.form.get('address', '').strip()
        chain = request.form.get('chain', '').strip()
        label = request.form.get('label', '').strip()
        
        if not address or not chain or not label:
            return jsonify({'error': 'All fields are required'}), 400
        
        if chain not in CHAINS:
            return jsonify({'error': 'Invalid chain selected'}), 400
        
        # Validate address format
        if not Web3.is_address(address):
            return jsonify({'error': 'Invalid wallet address format'}), 400
        
        # Check if wallet already exists
        for wallet in tracked_wallets:
            if wallet.address.lower() == address.lower() and wallet.chain == chain:
                return jsonify({'error': 'Wallet already being tracked'}), 400
        
        # Add new wallet
        new_wallet = WalletInfo(
            address=Web3.to_checksum_address(address),
            chain=chain,
            label=label,
            last_checked=datetime.now()
        )
        tracked_wallets.append(new_wallet)
        
        # Send welcome message
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            welcome_message = f"""
🎉 <b>New Wallet Added</b>

💼 Label: {label}
🌐 Chain: {CHAINS[chain]['name']}
📍 Address: {address[:10]}...{address[-10:]}
✅ Monitoring started

You'll receive alerts when this wallet has new activity!
"""
            tracker.send_telegram_alert(welcome_message)
        
        logger.info(f"Added wallet: {label} ({address}) on {chain}")
        return jsonify({'success': True, 'message': 'Wallet added successfully'})
        
    except Exception as e:
        logger.error(f"Error adding wallet: {e}")
        return jsonify({'error': 'Failed to add wallet'}), 500

@app.route('/remove_wallet', methods=['POST'])
def remove_wallet():
    """Remove a wallet from tracking"""
    try:
        address = request.json.get('address', '').strip()
        chain = request.json.get('chain', '').strip()
        
        if not address or not chain:
            return jsonify({'error': 'Address and chain are required'}), 400
        
        # Find and remove wallet
        for i, wallet in enumerate(tracked_wallets):
            if wallet.address.lower() == address.lower() and wallet.chain == chain:
                removed_wallet = tracked_wallets.pop(i)
                logger.info(f"Removed wallet: {removed_wallet.label}")
                return jsonify({'success': True, 'message': 'Wallet removed successfully'})
        
        return jsonify({'error': 'Wallet not found'}), 404
        
    except Exception as e:
        logger.error(f"Error removing wallet: {e}")
        return jsonify({'error': 'Failed to remove wallet'}), 500

@app.route('/api/wallets')
def get_wallets():
    """API endpoint to get all tracked wallets"""
    wallets_data = []
    for wallet in tracked_wallets:
        # Get current balance
        balance = tracker.get_wallet_balance(wallet.address, wallet.chain)
        tx_count = tracker.get_transaction_count(wallet.address, wallet.chain)
        
        wallets_data.append({
            'address': wallet.address,
            'chain': wallet.chain,
            'label': wallet.label,
            'last_checked': wallet.last_checked.isoformat(),
            'last_tx_hash': wallet.last_tx_hash,
            'balance': balance,
            'tx_count': tx_count
        })
    return jsonify(wallets_data)

@app.route('/api/transactions')
def get_transactions():
    """API endpoint to get recent transactions"""
    transactions_data = []
    for tx in recent_transactions[-20:]:  # Last 20 transactions
        tx_data = tx.copy()
        if 'timestamp' in tx_data and isinstance(tx_data['timestamp'], datetime):
            tx_data['timestamp'] = tx_data['timestamp'].isoformat()
        transactions_data.append(tx_data)
    return jsonify(transactions_data)

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'tracked_wallets': len(tracked_wallets),
        'connections': list(tracker.web3_connections.keys()),
        'telegram_configured': bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        'recent_transactions': len(recent_transactions)
    })

@app.route('/test_telegram')
def test_telegram():
    """Test Telegram integration"""
    try:
        message = f"""
🧪 <b>Test Message</b>

This is a test message from your Multi-Chain Wallet Tracker!

🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
✅ Bot is working correctly!
"""
        tracker.send_telegram_alert(message)
        return jsonify({'success': True, 'message': 'Test message sent to Telegram'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Create templates on startup
    create_templates()
    
    # Get port from environment variable (Render sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    
    # Log startup info
    logger.info(f"Starting Multi-Chain Wallet Tracker on port {port}")
    logger.info(f"Telegram configured: {bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)}")
    logger.info(f"Connected chains: {list(tracker.web3_connections.keys())}")
    
    # Run the app
    app.run(host='0.0.0.0', port=port, debug=False)
