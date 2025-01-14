# Python
import os
import ssl
import base64
import socket
import hashlib
from time import sleep

# Modules
import nmcli
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives import serialization, hashes

# GroundSeg modules
from log import Log

class Utils:
    def make_hash(file):
        h  = hashlib.sha256()
        b  = bytearray(128*1024)
        mv = memoryview(b)
        with open(file, 'rb', buffering=0) as f:
            while n := f.readinto(mv):
                h.update(mv[:n])
        return h.hexdigest()

    def check_patp(patp):
        # Make sure patp is string
        if type(patp) != str:
            return False

        # Remove sig from patp
        if patp.startswith("~"):
            patp = patp[1:]

        # patps cannot start with doz
        if patp.startswith("doz"):
            return False

        # valid
        pre = "dozmarbinwansamlitsighidfidlissogdirwacsabwissibrigsoldopmodfoglidhopdardorlorhodfolrintogsilmirholpaslacrovlivdalsatlibtabhanticpidtorbolfosdotlosdilforpilramtirwintadbicdifrocwidbisdasmidloprilnardapmolsanlocnovsitnidtipsicropwitnatpanminritpodmottamtolsavposnapnopsomfinfonbanmorworsipronnorbotwicsocwatdolmagpicdavbidbaltimtasmalligsivtagpadsaldivdactansidfabtarmonranniswolmispallasdismaprabtobrollatlonnodnavfignomnibpagsopralbilhaddocridmocpacravripfaltodtiltinhapmicfanpattaclabmogsimsonpinlomrictapfirhasbosbatpochactidhavsaplindibhosdabbitbarracparloddosbortochilmactomdigfilfasmithobharmighinradmashalraglagfadtopmophabnilnosmilfopfamdatnoldinhatnacrisfotribhocnimlarfitwalrapsarnalmoslandondanladdovrivbacpollaptalpitnambonrostonfodponsovnocsorlavmatmipfip"
        suf = "zodnecbudwessevpersutletfulpensytdurwepserwylsunrypsyxdyrnuphebpeglupdepdysputlughecryttyvsydnexlunmeplutseppesdelsulpedtemledtulmetwenbynhexfebpyldulhetmevruttylwydtepbesdexsefwycburderneppurrysrebdennutsubpetrulsynregtydsupsemwynrecmegnetsecmulnymtevwebsummutnyxrextebfushepbenmuswyxsymselrucdecwexsyrwetdylmynmesdetbetbeltuxtugmyrpelsyptermebsetdutdegtexsurfeltudnuxruxrenwytnubmedlytdusnebrumtynseglyxpunresredfunrevrefmectedrusbexlebduxrynnumpyxrygryxfeptyrtustyclegnemfermertenlusnussyltecmexpubrymtucfyllepdebbermughuttunbylsudpemdevlurdefbusbeprunmelpexdytbyttyplevmylwedducfurfexnulluclennerlexrupnedlecrydlydfenwelnydhusrelrudneshesfetdesretdunlernyrsebhulrylludremlysfynwerrycsugnysnyllyndyndemluxfedsedbecmunlyrtesmudnytbyrsenwegfyrmurtelreptegpecnelnevfes"

        # convert to array
        pre = [pre[i:i+3] for i in range(0, len(pre), 3)]
        suf = [suf[i:i+3] for i in range(0, len(suf), 3)]

        # Galaxy check
        if len(patp) == 3:
            return patp in suf

        # Split patp
        patp = patp.split("-")

        # Check if valid
        for p in patp:
            if len(p) == 6:
                if p[:3] not in pre:
                    return False
                if p[3:] not in suf:
                    return False
            else:
                return False

        return True

    def check_internet_access(addr):
        Log.log("Updater: Checking internet access")
        try:
            socket.setdefaulttimeout(3)
            host, port = addr.split(":")
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, int(port)))
            return True
        except Exception as e:
            Log.log(f"Updater: Check internet access error: {e}")
            return False

    def get_wifi_device():
        for d in nmcli.device():
            if d.device_type == 'wifi':
                return d.device
        return "none"

    def list_wifi_ssids():
        return [x.ssid for x in nmcli.device.wifi() if len(x.ssid) > 0]

    def wifi_connect(ssid, pwd):
        try:
            nmcli.device.wifi_connect(ssid, pwd)
            Log.log(f"WiFi: Connected to: {ssid}")
            return True
        except Exception as e:
            Log.log(f"WiFi: Failed to connect to network: {e}")
            return False

    def convert_pub(pub):
        converted = ""
        try:
            if pub != "":
                converted = pub.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                    ).decode("utf-8")
        except Exception as e:
            Log.log(f"Keygen: Failed to convert pubkey: {e}")

        return converted

    def decrypt_password(priv, pwd):
        decrypted = ""
        try:
            pwd_bstr = bytes(pwd,'utf-8')
            pwd_bytes = base64.b64decode(pwd_bstr)
            decrypted = priv.decrypt(pwd_bytes, PKCS1v15()).decode("utf-8")
        except Exception as e:
            Log.log(f"Keygen: Failed to decrypt password: {e}")

        return decrypted

    def compare_password(salt, password, pwHash):
        res = False
        try:
            encoded_str = (salt + password).encode('utf-8')
            this_hash = hashlib.sha512(encoded_str).hexdigest()
            res = this_hash == pwHash
        except Exception as e:
            Log.log("Login: Failed to compare passwords: {e}")

        return res

    def start_script():
        return """\
#!/bin/bash

set -eu
# set defaults
amesPort="34343"
httpPort="80"
loom="31"

# Find the first directory and start urbit with the ship therein
dirnames="*/"
dirs=( $dirnames )
dirname=''${dirnames[0]}

# Patp checker
check_patp() {
    patp="$1"
    pre="dozmarbinwansamlitsighidfidlissogdirwacsabwissibrigsoldopmodfoglidhopdardorlorhodfolrintogsilmirholpaslacrovlivdalsatlibtabhanticpidtorbolfosdotlosdilforpilramtirwintadbicdifrocwidbisdasmidloprilnardapmolsanlocnovsitnidtipsicropwitnatpanminritpodmottamtolsavposnapnopsomfinfonbanmorworsipronnorbotwicsocwatdolmagpicdavbidbaltimtasmalligsivtagpadsaldivdactansidfabtarmonranniswolmispallasdismaprabtobrollatlonnodnavfignomnibpagsopralbilhaddocridmocpacravripfaltodtiltinhapmicfanpattaclabmogsimsonpinlomrictapfirhasbosbatpochactidhavsaplindibhosdabbitbarracparloddosbortochilmactomdigfilfasmithobharmighinradmashalraglagfadtopmophabnilnosmilfopfamdatnoldinhatnacrisfotribhocnimlarfitwalrapsarnalmoslandondanladdovrivbacpollaptalpitnambonrostonfodponsovnocsorlavmatmipfip"
    suf="zodnecbudwessevpersutletfulpensytdurwepserwylsunrypsyxdyrnuphebpeglupdepdysputlughecryttyvsydnexlunmeplutseppesdelsulpedtemledtulmetwenbynhexfebpyldulhetmevruttylwydtepbesdexsefwycburderneppurrysrebdennutsubpetrulsynregtydsupsemwynrecmegnetsecmulnymtevwebsummutnyxrextebfushepbenmuswyxsymselrucdecwexsyrwetdylmynmesdetbetbeltuxtugmyrpelsyptermebsetdutdegtexsurfeltudnuxruxrenwytnubmedlytdusnebrumtynseglyxpunresredfunrevrefmectedrusbexlebduxrynnumpyxrygryxfeptyrtustyclegnemfermertenlusnussyltecmexpubrymtucfyllepdebbermughuttunbylsudpemdevlurdefbusbeprunmelpexdytbyttyplevmylwedducfurfexnulluclennerlexrupnedlecrydlydfenwelnydhusrelrudneshesfetdesretdunlernyrsebhulrylludremlysfynwerrycsugnysnyllyndyndemluxfedsedbecmunlyrtesmudnytbyrsenwegfyrmurtelreptegpecnelnevfes"
    [[ "${patp:0:1}" == "~" ]] && patp="${patp:1}"
    patp_arr=(${patp//-/ })

    [[ "${patp:0:3}" == "doz" ]] && return

    if [[ ${#patp} -eq 3 ]]; then
        [[ $suf == *"$patp"* ]] && echo "$patp" && return
    else
        for p in "${patp_arr[@]}"; do
            [[ ${#p} -eq 6 && $pre == *"${p:0:3}"* && $suf == *"${p:3:3}"* ]] || return
        done
        echo "$patp"
    fi
}

# Find a directory with a valid patp
for patp in *; do
    if [[ -d $patp ]]; then
        result=$(echo $(check_patp "$patp"))
        if [[ -n $result ]]; then
          dirname=$result
          break
        fi
    fi
done

# check args
for i in "$@"
do
case $i in
  -p=*|--port=*)
      amesPort="${i#*=}"
      shift
      ;;
   --http-port=*)
      httpPort="${i#*=}"
      shift
      ;;
   --loom=*)
      loom="${i#*=}"
      shift
      ;;
   --dirname=*)
      dirname="${i#*=}"
      shift
      ;;
esac
done

# If the container is not started with the `-i` flag
# then STDIN will be closed and we need to start
# Urbit/vere with the `-t` flag.
ttyflag=""
if [ ! -t 0 ]; then
echo "Running with no STDIN"
ttyflag="-t"
fi

# Check if there is a keyfile, if so boot a ship with its name, and then remove the key
if [ -e *.key ]; then
    # Get the name of the key
    keynames="*.key"
    keys=( $keynames )
    keyname=''${keys[0]}
    mv $keyname /tmp

    # Boot urbit with the key, exit when done booting
    vere $ttyflag -w $(basename $keyname .key) -k /tmp/$keyname -p $amesPort -x --http-port $httpPort --loom $loom

    # Remove the keyfile for security
    rm /tmp/$keyname
    rm *.key || true
fi

exec vere $ttyflag -p $amesPort --http-port $httpPort --loom $loom $dirname
"""
