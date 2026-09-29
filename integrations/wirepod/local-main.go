// Standalone service entry point. No SDK behavior control is acquired here.
package main

import (
    "context"
    "encoding/json"
    "fmt"
    "net"
    "os"
    "os/signal"
    "syscall"
    "time"

    "github.com/kercre123/zeroconf"
    "github.com/kercre123/wire-pod/chipper/pkg/initwirepod"
    "github.com/kercre123/wire-pod/chipper/pkg/vars"
    stt "github.com/kercre123/wire-pod/chipper/pkg/wirepod/stt/whisper"
    web "github.com/kercre123/wire-pod/chipper/pkg/wirepod/config-ws"
)

func lanInterface() ([]net.Interface, error) {
    ip := net.ParseIP(os.Getenv("VECTOR_HOST_IP"))
    if ip == nil || ip.IsLoopback() || ip.To4() == nil { return nil, fmt.Errorf("a robot LAN address is required") }
    interfaces, err := net.Interfaces()
    if err != nil { return nil, err }
    for _, iface := range interfaces {
        addrs, _ := iface.Addrs()
        for _, addr := range addrs {
            parsed, _, _ := net.ParseCIDR(addr.String())
            if parsed.Equal(ip) { return []net.Interface{iface}, nil }
        }
    }
    return nil, fmt.Errorf("robot LAN interface unavailable")
}
func probe(ifaces []net.Interface) error {
    resolver, err := zeroconf.NewResolver(zeroconf.SelectIfaces(ifaces))
    if err != nil { return err }
    ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
    defer cancel()
    entries := make(chan *zeroconf.ServiceEntry)
    if err = resolver.Browse(ctx, "_app-proto._tcp", "local.", entries); err != nil { return err }
    conflicts := []string{}
    for entry := range entries {
        if entry.HostName == "escapepod.local." || entry.Instance == "escapepod" {
            for _, ip := range entry.AddrIPv4 { conflicts = append(conflicts, ip.String()) }
        }
    }
    return json.NewEncoder(os.Stdout).Encode(map[string]interface{}{"hosts": conflicts})
}
func main() {
    syscall.Umask(0077)
    ifaces, err := lanInterface()
    if err != nil { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
    if len(os.Args) == 2 && os.Args[1] == "probe" {
        if err := probe(ifaces); err != nil { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
        return
    }
    // Exit when the owning app backend disappears, even after an unclean crash.
    parent := os.Getppid()
    go func() { for { time.Sleep(time.Second); if os.Getppid() != parent { os.Exit(0) } } }()
    if err := initwirepod.BeginWirepodSpecific(stt.Init, stt.STT, stt.Name); err != nil {
        fmt.Fprintln(os.Stderr, "wire-pod initialization failed:", err); os.Exit(1)
    }
    if !vars.APIConfig.PastInitialSetup { fmt.Fprintln(os.Stderr, "wire-pod configuration missing"); os.Exit(1) }
    go initwirepod.StartChipper()
    var server *zeroconf.Server
    if os.Getenv("VECTOR_DISABLE_ADVERTISE") != "1" {
        server, err = zeroconf.RegisterProxy("escapepod", "_app-proto._tcp", "local.", 8084, "escapepod", []string{os.Getenv("VECTOR_HOST_IP")}, []string{"txtv=0", "lo=1", "la=2"}, ifaces)
        if err != nil { fmt.Fprintln(os.Stderr, "wire-pod discovery failed"); os.Exit(1) }
    }
    stop := make(chan os.Signal, 1)
    signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
    go func() { <-stop; if server != nil { server.Shutdown() }; os.Exit(0) }()
    web.StartWebServer()
}
