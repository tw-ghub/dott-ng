terminal_window = """
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="ext/xterm.css" />
    <script src="ext/xterm.js"></script>
    <!-- LOAD THE FIT ADDON -->
    <script src="ext/xterm-addon-fit.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body { margin: 0; background: #1e1e1e; height: 100vh; overflow: hidden; }
        #terminal { width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="terminal"></div>
    <script>
        window.onload = function() {
            window.term = new Terminal({
                cursorBlink: true,
                theme: { background: '#10222c' },
                convertEol: true
            });

            const fitAddon = new FitAddon.FitAddon();
            window.term.loadAddon(fitAddon);
            window.term.open(document.getElementById('terminal'));
            window.term.focus();
            fitAddon.fit();

            function handleResize() {
                fitAddon.fit();

                const dims = {
                    cols: window.term.cols,
                    rows: window.term.rows
                };

                if (window.pyBridge) {
                    // send resize event to backend
                    window.pyBridge.send_to_pty(`DOTTNG_CTRL_RESIZE ${dims.rows} ${dims.cols}\\n`);

                    // send delayed signal to process group PIDs to resize apps executed within iPython
                    setTimeout(() => { window.pyBridge.emit_resize_signal(); }, 100);
                }
            }

            // Executes handleResize once after a 100ms delay to ensure DOM is ready
            setTimeout(handleResize, 100);

            // window.addEventListener('resize', () => fitAddon.fit());
            window.addEventListener('resize', handleResize);

            new QWebChannel(qt.webChannelTransport, function (channel) {
                window.pyBridge = channel.objects.pyBridge;
            });

            window.term.onData(data => {
                if (window.pyBridge) window.pyBridge.send_to_pty(data);
            });
        };
    </script>
</body>
</html>
"""

dottng_banner = """
            
 000000000000          0930 0920     00000000000000000000000000000000                               
 09000000000000     809000000000800  00000000800000060000000980000000                               
 090       30000   00 96        8760       9080            0990          58005    9889    2000009   
 0908       0000  75 731        23 32      0000            0980          0   02  70  0 808       20 
 0900       30907 00 01          03500     0000            0980         0     0  0  0 0   003337000 
 0908       20907 00404          05000     0000            0980         0  00 70 0  00  09    3     
 0908       0000   49 99        0310       0000            0980        09  90  90   0   0   0    00 
 090       80000   59  5        3 30       0000            0980        0  89 0  0   0   0    00  0  
 08000000000009     005088020080600        0000            0000    0  00  03  0    0 0   00000   0  
 00000000000           0000600009          0000            0000   00 306 50   003330  005     400   

 ---------------------------------------------------------------------------------------------------
  Welcome to the DOTT.NG Interactive Shell!                                      powered by iPython
 ---------------------------------------------------------------------------------------------------
"""

dottng_notice = "  This an early beta version. Features and behavior might change without notice in future releases!"