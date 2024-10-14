package main

import (
	"errors"
	"io"
	"log"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"
	"time"
)

var (
	timeout = 5 * time.Minute

	totalRead = atomic.Uint64{}
)

func zfssend() (cmd *exec.Cmd, rp *os.File, err error) {
	var wp *os.File

	rp, wp, err = os.Pipe()
	if err != nil {
		return
	}
	defer wp.Close()

	args := []string{"send"}
	args = append(args, os.Args[1:]...)

	cmd = exec.Command("zfs", args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = wp
	cmd.Stderr = os.Stderr

	err = cmd.Start()

	return
}

func wrapwriter(out *os.File, wg *sync.WaitGroup) (wp *os.File, err error) {
	if err = out.SetWriteDeadline(time.Now().Add(time.Second)); err == nil {
		return out, nil
	}

	var rp *os.File

	rp, wp, err = os.Pipe()
	if err != nil {
		return
	}

	wg.Add(1)
	go func() {
		defer wg.Done()
		defer rp.Close()
		defer out.Close()

		if _, err := io.Copy(out, rp); err != nil {
			log.Printf("wrapwriter: io.Copy failed: %+v", err)
			os.Exit(11)
		}
	}()

	return
}

func main() {
	wg := &sync.WaitGroup{}

	cmd, inp, err := zfssend()
	if err != nil {
		log.Fatal(err)
	}
	outp, err := wrapwriter(os.Stdout, wg)
	if err != nil {
		log.Fatal(err)
	}

	if err = inp.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
		log.Fatalf("failed setting read deadline: %+v", err)
	}
	if err = outp.SetWriteDeadline(time.Now().Add(time.Second)); err != nil {
		log.Fatalf("failed setting write deadline: %+v", err)
	}

	wg.Add(1)
	go func() {
		defer wg.Done()
		defer outp.Close()

		buf := make([]byte, 1<<20)

		for {
			_ = inp.SetReadDeadline(time.Now().Add(timeout))
			n, err := inp.Read(buf)
			if n == 0 && errors.Is(err, io.EOF) {
				return
			}
			if err != nil {
				if errors.Is(err, os.ErrDeadlineExceeded) {
					log.Printf("timeout on read, killing process after %d successful bytes read", totalRead.Load())
					if err := cmd.Process.Kill(); err != nil {
						log.Fatal(err)
					}
				}

				return
			}
			if n == 0 {
				log.Fatal("short read")
			}

			totalRead.Add(uint64(n))

			_ = outp.SetWriteDeadline(time.Now().Add(timeout))
			wn, err := outp.Write(buf[:n])
			if err != nil {
				if errors.Is(err, os.ErrDeadlineExceeded) {
					log.Printf("timeout on write, killing process")
					if err := cmd.Process.Kill(); err != nil {
						log.Fatal(err)
					}
				}

				if wn != n {
					log.Fatal("short write")
				}
			}
		}
	}()

	wg.Wait()

	cmd.Wait()

	os.Exit(cmd.ProcessState.ExitCode())
}
