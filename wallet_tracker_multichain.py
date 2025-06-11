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
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')

# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
ALCHEMY_API_KEY = os.environ.get('ALCHEMY_API_KEY', '')

# Blockchain configurations
CHAINS = {
    'ethereum': {
        'name': 'Ethereum',
        'rpc_url': f'https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}',
        'explorer': 'https://etherscan.io',
        'chain_id': 1
    },
    'polygon': {
        'name': 'Polygon',
        'rpc_url': f'https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}',
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
    
    def get_latest_transaction(self, address: str, chain: str) -> Optional[Dict]:
        """Get the latest transaction for an address on a specific chain"""
        try:
            if chain not in self.web3_connections:
                return None
            
            w3 = self.web3_connections[chain]
            
            # Get the latest block
            latest_block = w3.eth.get_block('latest', full_transactions=True)
            
            # Check transactions in the latest block
            for tx in latest_block.transactions:
                if tx['from'].lower() == address.lower() or tx['to'] and tx['to'].lower() == address.lower():
                    return {
                        'hash': tx['hash'].hex(),
                        'from': tx['from'],
                        'to': tx['to'],
                        'value': str(tx['value']),
                        'block_number': tx['blockNumber'],
                        'timestamp': latest_block.timestamp,
                        'chain': chain
                    }
            
            return None
        except Exception as e:
            logger.error(f"Error getting transaction for {address} on {chain}: {e}")
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
            response = requests.post(url, data=data)
            if response.status_code == 200:
                logger.info("Telegram alert sent successfully")
            else:
                logger.error(f"Failed to send Telegram alert: {response.text}")
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
    
    def monitor_wallet(self, wallet: WalletInfo):
        """Monitor a single wallet for new transactions"""
        try:
            latest_tx = self.get_latest_transaction(wallet.address, wallet.chain)
            
            if latest_tx and latest_tx['hash'] != wallet.last_tx_hash:
                # New transaction found
                wallet.last_tx_hash = latest_tx['hash']
                wallet.last_checked = datetime.now()
                
                # Add to recent transactions
                recent_transactions.append({
                    'wallet_label': wallet.label,
                    'address': wallet.address,
                    'chain': wallet.chain,
                    'tx_hash': latest_tx['hash'],
                    'from': latest_tx['from'],
                    'to': latest_tx['to'],
                    'value': latest_tx['value'],
                    'timestamp': datetime.fromtimestamp(latest_tx['timestamp']),
                    'explorer_url': f"{CHAINS[wallet.chain]['explorer']}/tx/{latest_tx['hash']}"
                })
                
                # Send Telegram alert
                chain_name = CHAINS[wallet.chain]['name']
                message = f"""
🔔 <b>New Transaction Alert</b>

💼 Wallet: {wallet.label}
🌐 Chain: {chain_name}
📍 Address: {wallet.address[:10]}...{wallet.address[-10:]}
💰 Value: {Web3.from_wei(int(latest_tx['value']), 'ether'):.6f} ETH
🔗 <a href="{CHAINS[wallet.chain]['explorer']}/tx/{latest_tx['hash']}">View Transaction</a>
"""
                self.send_telegram_alert(message)
                logger.info(f"New transaction detected for {wallet.label}")
            
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
            time.sleep(30)  # Check every 30 seconds
        except Exception as e:
            logger.error(f"Error in background monitor: {e}")
            time.sleep(60)  # Wait longer on error

# Start background monitoring
monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# Routes
@app.route('/')
def index():
    """Main dashboard"""
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
        wallets_data.append({
            'address': wallet.address,
            'chain': wallet.chain,
            'label': wallet.label,
            'last_checked': wallet.last_checked.isoformat(),
            'last_tx_hash': wallet.last_tx_hash
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
        'connections': list(tracker.web3_connections.keys())
    })

# Create templates directory and HTML template
@app.before_first_request
def create_templates():
    """Create templates directory and basic HTML template"""
    import os
    
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
        <h1 class="text-4xl font-bold text-center mb-8 text-gray-800">Multi-Chain Wallet Tracker</h1>
        
        <!-- Add Wallet Form -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-2xl font-semibold mb-4">Add New Wallet</h2>
            <form id="addWalletForm" class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <input type="text" id="address" placeholder="Wallet Address" class="px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" required>
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
            <h2 class="text-2xl font-semibold mb-4">Tracked Wallets ({{ wallets|length }})</h2>
            <div id="walletsList" class="space-y-4">
                {% for wallet in wallets %}
                <div class="border rounded-lg p-4 bg-gray-50">
                    <div class="flex justify-between items-center">
                        <div>
                            <h3 class="font-semibold text-lg">{{ wallet.label }}</h3>
                            <p class="text-gray-600 text-sm">{{ wallet.address }}</p>
                            <p class="text-gray-500 text-xs">{{ chains[wallet.chain]['name'] }} • Last checked: {{ wallet.last_checked.strftime('%Y-%m-%d %H:%M:%S') }}</p>
                        </div>
                        <button onclick="removeWallet('{{ wallet.address }}', '{{ wallet.chain }}')" class="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition-colors">Remove</button>
                    </div>
                </div>
                {% endfor %}
                {% if not wallets %}
                <p class="text-gray-500 text-center py-8">No wallets being tracked yet. Add one above!</p>
                {% endif %}
            </div>
        </div>
        
        <!-- Recent Transactions -->
        <div class="bg-white rounded-lg shadow-md p-6">
            <h2 class="text-2xl font-semibold mb-4">Recent Transactions</h2>
            <div class="space-y-4">
                {% for tx in recent_transactions %}
                <div class="border-l-4 border-blue-500 pl-4 py-2">
                    <div class="flex justify-between items-start">
                        <div>
                            <h4 class="font-semibold">{{ tx.wallet_label }}</h4>
                            <p class="text-sm text-gray-600">{{ tx.chain|title }} • {{ tx.timestamp.strftime('%Y-%m-%d %H:%M:%S') if tx.timestamp else 'N/A' }}</p>
                            <p class="text-xs text-gray-500">{{ tx.tx_hash[:20] }}...</p>
                        </div>
                        <a href="{{ tx.explorer_url }}" target="_blank" class="text-blue-500 hover:text-blue-700 text-sm">View →</a>
                    </div>
                </div>
                {% endfor %}
                {% if not recent_transactions %}
                <p class="text-gray-500 text-center py-8">No transactions detected yet.</p>
                {% endif %}
            </div>
        </div>
    </div>
    
    <script>
        // Add wallet form handler
        document.getElementById('addWalletForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
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
                    alert('Wallet added successfully!');
                    location.reload();
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (error) {
                alert('Error adding wallet: ' + error.message);
            }
        });
        
        // Remove wallet function
        async function removeWallet(address, chain) {
            if (!confirm('Are you sure you want to remove this wallet?')) return;
            
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
                    alert('Wallet removed successfully!');
                    location.reload();
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (error) {
                alert('Error removing wallet: ' + error.message);
            }
        }
        
        // Auto-refresh every 60 seconds
        setInterval(() => {
            location.reload();
        }, 60000);
    </script>
</body>
</html>'''
    
    # Write template file
    template_path = os.path.join(templates_dir, 'index.html')
    with open(template_path, 'w') as f:
        f.write(html_template)

if __name__ == '__main__':
    # Get port from environment variable (Render sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    
    # Run the app
    app.run(host='0.0.0.0', port=port, debug=False)
