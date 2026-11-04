import 'package:flutter/material.dart';
import 'widgets/backend_status_card.dart';

void main() => runApp(const IthutePayApp());

const _navy = Color(0xFF101A35);
const _blue = Color(0xFF275DE5);
const _surface = Color(0xFFF5F7FC);

class IthutePayApp extends StatelessWidget {
  const IthutePayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'IthutePay',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: _blue),
        scaffoldBackgroundColor: _surface,
        appBarTheme: const AppBarTheme(backgroundColor: Colors.white, foregroundColor: _navy),
      ),
      home: const PayHomePage(),
    );
  }
}

class PayHomePage extends StatefulWidget {
  const PayHomePage({super.key});

  @override
  State<PayHomePage> createState() => _PayHomePageState();
}

class _PayHomePageState extends State<PayHomePage> {
  int _selected = 0;

  static const _labels = ['Home', 'Activity', 'Cards', 'Profile'];
  static const _icons = [
    Icons.home_rounded,
    Icons.receipt_long_rounded,
    Icons.credit_card_rounded,
    Icons.person_outline_rounded,
  ];

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 760;
    final content = _selected == 0
        ? const _HomeContent()
        : _InformationPage(
            icon: _icons[_selected],
            title: _labels[_selected],
            message: 'This section will be available after secure account '
                'integration and testing.',
          );

    return Scaffold(
      appBar: AppBar(
        title: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.account_balance_wallet_rounded, color: _blue),
            SizedBox(width: 10),
            Text('IthutePay', style: TextStyle(fontWeight: FontWeight.w800)),
          ],
        ),
        actions: [
          if (wide)
            const Padding(
              padding: EdgeInsets.only(right: 24),
              child: Center(
                child: Text('Mobile & web preview',
                    style: TextStyle(color: Color(0xFF63718E))),
              ),
            ),
        ],
      ),
      body: Row(
        children: [
          if (wide)
            NavigationRail(
              backgroundColor: Colors.white,
              selectedIndex: _selected,
              onDestinationSelected: (value) => setState(() => _selected = value),
              labelType: NavigationRailLabelType.all,
              destinations: List.generate(
                _labels.length,
                (index) => NavigationRailDestination(
                  icon: Icon(_icons[index]),
                  label: Text(_labels[index]),
                ),
              ),
            ),
          Expanded(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 850),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(20, 28, 20, 40),
                  child: content,
                ),
              ),
            ),
          ),
        ],
      ),
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: _selected,
              onDestinationSelected: (value) => setState(() => _selected = value),
              destinations: List.generate(
                _labels.length,
                (index) => NavigationDestination(
                  icon: Icon(_icons[index]),
                  label: _labels[index],
                ),
              ),
            ),
    );
  }
}

class _HomeContent extends StatelessWidget {
  const _HomeContent();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Welcome to IthutePay',
            style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: _navy)),
        const SizedBox(height: 6),
        const Text('Simple, secure payments for Lesotho.',
            style: TextStyle(fontSize: 15, color: Color(0xFF63718E))),
        const SizedBox(height: 24),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(26),
          decoration: BoxDecoration(
            gradient: const LinearGradient(colors: [_navy, Color(0xFF263D7C)]),
            borderRadius: BorderRadius.circular(24),
          ),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('YOUR WALLET', style: TextStyle(color: Colors.white70, letterSpacing: 2)),
              SizedBox(height: 18),
              Text('Balance unavailable',
                  style: TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.bold)),
              SizedBox(height: 8),
              Text('Connect your verified account to see balances.',
                  style: TextStyle(color: Colors.white70)),
              SizedBox(height: 14),
              Row(children: [
                Icon(Icons.lock_outline, color: Colors.white70, size: 17),
                SizedBox(width: 6),
                Text('No live transactions in preview',
                    style: TextStyle(color: Colors.white70, fontSize: 12)),
              ]),
            ],
          ),
        ),
        const SizedBox(height: 16),
        const BackendStatusCard(),
        const SizedBox(height: 26),
        const Text('Payment services',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: _navy)),
        const SizedBox(height: 14),
        LayoutBuilder(builder: (context, box) {
          final columns = box.maxWidth >= 600 ? 4 : 2;
          return GridView.count(
            crossAxisCount: columns,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.28,
            children: const [
              _ActionTile(Icons.send_rounded, 'Send money'),
              _ActionTile(Icons.call_received_rounded, 'Receive'),
              _ActionTile(Icons.qr_code_scanner_rounded, 'Scan & pay'),
              _ActionTile(Icons.receipt_rounded, 'Pay bills'),
            ],
          );
        }),
        const SizedBox(height: 22),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: const Color(0xFFEAF0FF),
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Row(
            children: [
              Icon(Icons.info_outline, color: _blue),
              SizedBox(width: 12),
              Expanded(child: Text(
                'Preview mode: payments, balances and account sign-in are not enabled.',
                style: TextStyle(color: _navy),
              )),
            ],
          ),
        ),
      ],
    );
  }
}

class _ActionTile extends StatelessWidget {
  final IconData icon;
  final String label;
  const _ActionTile(this.icon, this.label);

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$label (coming soon)',
      child: Card(
        elevation: 0,
        color: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(17)),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: _blue, size: 30),
            const SizedBox(height: 10),
            Text(label, textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.w600, color: _navy)),
            const SizedBox(height: 4),
            const Text('Coming soon',
                style: TextStyle(fontSize: 11, color: Color(0xFF63718E))),
          ],
        ),
      ),
    );
  }
}

class _InformationPage extends StatelessWidget {
  final IconData icon;
  final String title;
  final String message;
  const _InformationPage({
    required this.icon,
    required this.title,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 58, horizontal: 24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
      ),
      child: Column(
        children: [
          Icon(icon, color: _blue, size: 64),
          const SizedBox(height: 20),
          Text(title, style: const TextStyle(
            fontSize: 24, fontWeight: FontWeight.bold, color: _navy,
          )),
          const SizedBox(height: 8),
          Text(message, textAlign: TextAlign.center,
            style: const TextStyle(color: Color(0xFF63718E))),
        ],
      ),
    );
  }
}
