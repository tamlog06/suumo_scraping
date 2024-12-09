from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.service import Service

from tqdm import tqdm
import re
import os

import smtplib
import my_gmail_account as my_gmail
from email.mime.text import MIMEText
from email.utils import formatdate

from configs import EXECUTABLE_PATH, TARGET_MONTHS, BASE_URL

def send_email(title, move_in_date, fee, url):
    connection = smtplib.SMTP("smtp.gmail.com", 587)
    connection.starttls()
    connection.login(my_gmail.YOUR_GMAIL_ADDRESS, my_gmail.APP_PASSWORD)
    
    # Create message object
    msg = MIMEText(
        f"新着物件\n物件名:{title}\n家賃:{fee/10000}万円\n入居可能日:{move_in_date}\n\n{url}",
        'plain',
        'utf-8'
    )
    
    # Set email headers
    msg['Subject'] = f"新着物件通知: {move_in_date}-{fee/10000}万円-{title}"
    msg['From'] = my_gmail.YOUR_GMAIL_ADDRESS
    msg['To'] = my_gmail.YOUR_GMAIL_ADDRESS
    msg['Date'] = formatdate()
    
    try:
        # Send email
        connection.send_message(msg)
    
    except Exception as e:
        print(f"メール送信エラー: {str(e)}")
    
    finally:
        # Close connection
        connection.quit()


def check_target_month(text):
    """入居可能月がTARGET_MONTHSに入っているかどうかを確認"""
    # 月とその時期（上旬、中旬、下旬）をマッチする正規表現
    month_expression = re.search(r"(\d+)月(上旬|中旬|下旬)?", text)
    
    if month_expression:
        month = int(month_expression.group(1))  # 月（数字部分）
        period = month_expression.group(2)
        
        # 数字の月がTARGET_MONTHSに含まれているかチェック
        if month in TARGET_MONTHS:
            return True
        
        # 文字列（上旬、中旬、下旬）に特定の時期が含まれている場合
        if isinstance(period, str):  # 上旬、中旬、下旬があれば
            target_str = f"{month}月{period}"
            if target_str in TARGET_MONTHS:
                return True
    
    return False


def count_total_properties(driver):
    """全ページを巡回して総物件数を数える"""
    total_properties = 0
    max_page = 1
    all_property_links = []
    links_per_page = []
    
    print("Counting total properties across all pages...")
    
    page = 1
    while True:
        current_url = f"{BASE_URL}&page={page}" if page > 1 else BASE_URL
        driver.get(current_url)
        
        # 物件リンクを取得
        detail_links = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "a.js-cassette_link_href[target='_blank']")
            )
        )
        
        # このページの物件数を加算
        page_properties = len(detail_links)
        total_properties += page_properties
        links_per_page.append(page_properties)
        
        # 物件のURLを保存
        page_links = [link.get_attribute('href') for link in detail_links]
        all_property_links.extend(page_links)
        
        print(f"Page {page}: Found {page_properties} properties")
        
        # 次へボタンがあるかどうか確認
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, "p.pagination-parts a")
            txt = [button.text for button in buttons]
            if "次へ" in txt:
                page += 1
                max_page = page
            else:
                break
        except NoSuchElementException:
            break
    
    print(f"\nTotal pages: {max_page}")
    print(f"Total properties: {total_properties}")
    
    return max_page, total_properties, all_property_links, links_per_page

def process_property_details(driver, property_url, pbar):
    try:
        # 新しいタブで開く
        driver.execute_script(f"window.open('{property_url}', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])


        # 物件の要素を待機して取得
        try:
            title = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1.section_h1-header-title"))
            ).text

            # 家賃を含むdiv要素を待機して取得
            rent_element = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "span.property_view_note-emphasis"))
            )
            rent_text = rent_element.text
            # 数値のみを取得（"14万円" → 140000）
            rent = int(float(rent_text.replace('万円', '')) * 10000)

            # 管理費・共益費を含むspan要素を待機して取得
            management_fee_element = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '管理費・共益費')]"))
            )
            management_fee_text = management_fee_element.text
            # 数値のみを取得
            management_fee = int(''.join(filter(str.isdigit, management_fee_text)))

            move_in_element = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//th[text()='入居']"))
            )

            # 対応するtd要素を取得
            move_in_date = move_in_element.find_element(By.XPATH, "following-sibling::td").text

            pbar.set_description(f"Processing: {title}")
            if check_target_month(move_in_date):
                pbar.set_description(f"Found: {title}-{move_in_date}")

                # txtファイルに保存
                if not os.path.exists(f"物件候補/{move_in_date}-{(rent+management_fee)/10000}万円-{title}.txt"):
                    with open(f"物件候補/{move_in_date}-{(rent+management_fee)/10000}万円-{title}.txt", "w") as f:
                        f.write(f"{property_url}\n")

                    # メールで送信
                    send_email(title, move_in_date, rent+management_fee, property_url)

        except Exception as e:
            pbar.set_description(f"Error getting title: {str(e)[:30]}...")

        driver.close() # タブを閉じる
        driver.switch_to.window(driver.window_handles[0])

        pbar.update(1)

    except Exception as e:
        pbar.write(f"Error processing property: {str(e)}")
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        pbar.update(1)

def main():
    os.makedirs("物件候補", exist_ok=True)

    options = webdriver.ChromeOptions()
    #  options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--headless")

    driver = webdriver.Chrome(
        options=options,
        service=Service(EXECUTABLE_PATH)
    )

    try:
        # まず全ページを巡回して総数を取得
        max_pages, total_properties, all_property_links, links_per_page = count_total_properties(driver)

        with tqdm(total=max_pages, desc="Pages", position=0) as pbar_pages:
            with tqdm(total=total_properties, desc="Properties", position=1) as pbar_properties:
                # 保存したURLを使用して物件を処理
                properties_processed = 0
                current_page = 1
                
                for property_url in all_property_links:
                    process_property_details(driver, property_url, pbar_properties)
                    properties_processed += 1
                    
                    # ページの更新
                    if properties_processed  == sum(links_per_page[:current_page]):
                        pbar_pages.update(1)
                        current_page += 1
                
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        
    finally:
        print("\nClosing browser...")
        driver.quit()

if __name__ == "__main__":
    main()

