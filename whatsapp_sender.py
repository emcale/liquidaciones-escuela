def enviar_whatsapp_selenium(nombre, telefono, mensaje, driver=None):
    import os
    import time
    import urllib.parse
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    PERFIL_WHATSAPP = os.path.join(os.getcwd(), "whatsapp_session")

    # 🔹 Crear driver SOLO si no existe
    if driver is None:
        options = Options()
        options.add_argument(f"--user-data-dir={PERFIL_WHATSAPP}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--start-maximized")

        driver = webdriver.Chrome(options=options)
        driver.get("https://web.whatsapp.com")

        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.ID, "side"))
        )

    wait = WebDriverWait(driver, 25)

    numero = telefono.replace("+", "").replace(" ", "").replace("-", "")

    mensaje_codificado = urllib.parse.quote(mensaje)

    url = (
        f"https://web.whatsapp.com/send"
        f"?phone={numero}"
        f"&text={mensaje_codificado}"
    )

    driver.get(url)

    # 🔴 1️⃣ Detectar número inválido
    try:
        error_box = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[contains(text(),'no está en WhatsApp')]")
            )
        )

        print(f"❌ Número inválido: {nombre}")
        driver.get("https://web.whatsapp.com")
        return driver, False  # 👈 DEVOLVEMOS ERROR

    except TimeoutException:
        pass  # No apareció error → seguimos

    # 🟢 2️⃣ Intentar enviar mensaje
    try:
        input_msg = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//footer//div[@contenteditable='true']")
            )
        )

        time.sleep(1)
        input_msg.send_keys(Keys.ENTER)

        print(f"✅ WhatsApp enviado a {nombre}")
        time.sleep(3)

        driver.get("https://web.whatsapp.com")
        return driver, True  # 👈 ENVÍO OK

    except Exception as e:
        print(f"❌ Error enviando a {nombre}: {e}")
        driver.get("https://web.whatsapp.com")
        return driver, False