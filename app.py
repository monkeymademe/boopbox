from flask import Flask, render_template, request, jsonify, g, flash, redirect
from apscheduler.schedulers.background import BackgroundScheduler
import requests, feedparser
import os
import datetime
from inky import InkyWHAT
import logging
from threading import Lock
from PIL import Image, ImageFont, ImageDraw
from font_source_serif_pro import SourceSerifProSemibold
from font_source_sans_pro import SourceSansProSemibold
import textwrap
import json

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load the configuration
def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

# Save configuration function
def save_config(config):
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

# Example usage
config = load_config()

# Accessing the values
feeds = config['feeds']
birthdate = config['birthdate']
weather_api_key = config['weather_api_key']

print("Feeds:", feeds)
print("Birthdate:", birthdate)
print("Weather API Key:", weather_api_key)

app = Flask(__name__)
app.secret_key = 'raspberryjamberlin'  # Set a secret key for session management

# Global variables with locks for thread safety
status_lock = Lock()
articlecount_lock = Lock()


job_running = True
PATH = os.path.dirname(__file__)
status = 'true'
bbc_feed = 'Feed was not fetched yet'
articlecount = 0
current_displayed_article = None

# Function to safely set status with a lock
def set_status(new_status):
    global status
    with status_lock:
        status = new_status

# Function to safely get status with a lock
def get_status():
    with status_lock:
        return status

def fetch_and_filter_feeds():
    global global_feeds
    global_feeds = []  # Reset the global feeds

    for feed_info in feeds:
        feed_url = feed_info['url']
        article_count = int(feed_info.get('article_count', 5))  # Ensure it's an integer
        logging.info(f"Fetching feed: {feed_url}")

        try:
            feed = feedparser.parse(feed_url)

            # Check for parsing errors
            if feed.bozo:
                raise ValueError(f"Feed parsing failed for {feed_url}: {feed.bozo_exception}")

            # Append the title and the specified number of entries
            global_feeds.append({
                'title': feed.feed.title,
                'entries': feed.entries[:article_count]  # Fetch only the specified number of articles
            })

        except Exception as e:
            logging.error(f"Failed to fetch feed {feed_url}: {e}")

def get_bbc_feed():
    global bbc_feed
    logging.info("Fetching BBC news feed...")
    try:
        feed = feedparser.parse("http://feeds.bbci.co.uk/news/rss.xml")
        if 'bozo_exception' in feed:
            raise ValueError(f"Feed parsing failed: {feed.bozo_exception}")
        bbc_feed = feed["entries"][:10]  # Fetch only the first 10 articles
    except Exception as e:
        logging.error(f"Failed to fetch the feed: {e}")
        bbc_feed = "Error fetching the feed"

def get_articles():
    global articlecount, current_displayed_article  # Add the current_displayed_article variable
    with articlecount_lock:
        if global_feeds and isinstance(global_feeds, list) and len(global_feeds) > 0:
            all_articles = []
            for feed in global_feeds:
                # Ensure we are accessing the 'entries' key correctly
                if 'entries' in feed and isinstance(feed['entries'], list):
                    all_articles.extend(feed['entries'])

            # Check if there are articles to print
            if all_articles:
                article = all_articles[articlecount % len(all_articles)]
                title = article.get('title', 'No title available')
                summary = article.get('summary', 'No summary available')
                
                # Update the currently displayed article
                current_displayed_article = {
                    'title': title,
                    'summary': summary
                }

                print_article_inky(title, summary)
                print(f"Printing the following Article: {title}")
                articlecount = (articlecount + 1) % len(all_articles)  # Wrap around article count
            else:
                logging.warning("No articles found in the feeds.")
        else:
            logging.warning("No feeds available or feeds are empty.")

@app.route("/")
def home():
    global global_feeds
    return render_template("home.html", global_feeds=global_feeds, current_displayed_article=current_displayed_article, status=get_status(), title="Home")

@app.route("/feeds")
def feeds_page():
    global global_feeds
    return render_template("feeds.html", global_feeds=global_feeds, enumerate=enumerate, status=get_status(), title="feeds")

@app.route("/settings", methods=["GET", "POST"])
def settings():
    config = load_config()
    
    if request.method == "POST":
        new_feed = request.form.get("new_feed")
        if new_feed:
            # Validate the feed URL
            feed = feedparser.parse(new_feed)
            if not feed.bozo:
                config['feeds'].append(new_feed)
                save_config(config)
                flash("Feed added successfully!", "success")
            else:
                flash("Invalid feed URL!", "danger")
        
        # Remove feed
        feed_to_remove = request.form.get("remove_feed")
        if feed_to_remove in config['feeds']:
            config['feeds'].remove(feed_to_remove)
            save_config(config)
            flash("Feed removed successfully!", "success")
    
    return render_template("settings.html", feeds=config['feeds'])

@app.route('/push_article', methods=['POST'])
def push_article():
    feed_title = request.form.get('feed_title')
    index = int(request.form.get('index'))  # Convert index to int

    # Find the corresponding article in global_feeds
    for feed in global_feeds:
        if feed['title'] == feed_title:
            if 0 <= index < len(feed['entries']):  # Ensure the index is valid
                article = feed['entries'][index]
                title = article.title
                summary = article.summary
                print_article_inky(title, summary)
                return jsonify(success=True)
    
    return jsonify(success=False), 404

@app.route('/add_feed', methods=['POST'])
def add_feed():
    feed_url = request.form['feedUrl']
    article_count = 5  # Default to 5 articles
    
    # Load existing config
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Add new feed
    config['feeds'].append({
        'url': feed_url,
        'article_count': article_count
    })
    
    # Save updated config
    with open('config.json', 'w') as f:
        json.dump(config, f)
    
    return redirect('/settings')

@app.route('/update_feed', methods=['POST'])
def update_feed():
    data = request.get_json()
    url = data['url']
    new_count = data['article_count']
    
    # Load existing config
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Update the article count for the feed
    for feed in config['feeds']:
        if feed['url'] == url:
            feed['article_count'] = new_count
    
    # Save updated config
    with open('config.json', 'w') as f:
        json.dump(config, f)
    
    return jsonify(success=True)

@app.route('/remove_feed', methods=['POST'])
def remove_feed():
    data = request.get_json()
    url = data['url']
    
    # Load existing config
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Remove the feed
    config['feeds'] = [feed for feed in config['feeds'] if feed['url'] != url]
    
    # Save updated config
    with open('config.json', 'w') as f:
        json.dump(config, f)
    
    return jsonify(success=True)

@app.route('/process', methods=['POST'])
def process():
    if get_status() == 'false':
        return jsonify({'error': 'Operation not allowed!'}), 400
    
    text = request.form.get('text', '').strip()
    if not text:
        return jsonify({'error': 'Missing text!'}), 400
    
    set_status('false')
    try:
        processed_text = text.upper()
        inkyprint(processed_text)
        response = {'message': 'Text processed successfully!'}
    finally:
        set_status('true')
    
    return jsonify(response)

def reflow_text(text, max_width, font, draw):
    words = text.split(" ")
    lines = []
    current_line = ""

    for word in words:
        # Check the width of the current line plus the new word
        test_line = f"{current_line} {word}".strip()
        # Use textbbox to calculate the width of the test line
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]  # Width is the difference between right and left x-coordinates

        if width <= max_width:
            current_line = test_line  # Add the word to the current line
        else:
            # If adding the word exceeds the width, start a new line
            if current_line:  # Avoid adding empty lines
                lines.append(current_line)
            current_line = word

    # Add the last line if there is any remaining text
    if current_line:
        lines.append(current_line)

    # Join lines with newline characters
    return "\n".join(lines)

def inkyprint(message):
    # Set up the correct display and scaling factors
    inky_display = InkyWHAT('red')
    inky_display.set_border(inky_display.WHITE)

    w = inky_display.WIDTH
    h = inky_display.HEIGHT

    # Create a new canvas to draw on
    img = Image.new("P", (w, h))
    draw = ImageDraw.Draw(img)

    # Load the fonts
    font_size = 24
    quote_font = ImageFont.truetype(SourceSansProSemibold, font_size)

    # The amount of padding around the quote
    padding = 50
    max_width = w - padding  # Total width available for text

    # Reflow the quote text to fit the width
    reflowed = reflow_text(message, max_width, quote_font, draw)

    # Get the bounding box for the reflowed text
    bbox = draw.textbbox((0, 0), reflowed, font=quote_font)
    p_h = bbox[3]  # Height is the fourth value

    # x- and y-coordinates for the quote
    quote_x = (w - max_width) / 2
    quote_y = (h - p_h) / 2

    # Draw red rectangles top and bottom to frame the quote
    draw.rectangle((padding / 4, padding / 4, w - (padding / 4), quote_y - (padding / 4)), fill=inky_display.RED)
    draw.rectangle((padding / 4, quote_y + p_h + (padding / 4), w - (padding / 4), h - (padding / 4)), fill=inky_display.RED)

    # Add some white hatching to the red rectangles to make it look a bit more interesting
    hatch_spacing = 12
    for x in range(0, 2 * w, hatch_spacing):
        draw.line((x, 0, x - w, h), fill=inky_display.WHITE, width=3)

    # Write the quote to the canvas
    draw.multiline_text((quote_x, quote_y), reflowed, fill=inky_display.BLACK, font=quote_font, align="left")
    
    # Display the completed canvas on Inky wHAT
    inky_display.set_image(img)
    inky_display.show()
    
    # Save the image
    img.putpalette((255, 255, 255, 0, 0, 0, 255, 0, 0) + (0, 0, 0) * 252)
    img = img.convert("RGB").quantize(palette=img)
    img.save('/home/pi/boopbox/static/img/inkyscreen.png')

def print_article_inky(headline, summary):
    global status
    if status == 'true':
        # Set up the correct display and scaling factors
        inky_display = InkyWHAT('red')
        inky_display.set_border(inky_display.WHITE)

        # inky_display.set_rotation(180)
        w = inky_display.WIDTH
        h = inky_display.HEIGHT

        # Create a new canvas to draw on
        img = Image.new("P", (inky_display.WIDTH, inky_display.HEIGHT))
        draw = ImageDraw.Draw(img)

        # Load the fonts
        font_size = 14
        headline_font = ImageFont.truetype(SourceSerifProSemibold, 24)
        summary_font = ImageFont.truetype(SourceSerifProSemibold, 18)

        # Padding around the entry
        padding = 50
        max_width = w - padding

        # Reflow the headline and summary text to fit the width
        reflowed_headline = reflow_text(headline, max_width - 0, headline_font, draw)
        reflowed_summary = reflow_text(summary, max_width - 0, summary_font, draw)

        # Get the bounding box for the headline and summary text
        headline_bbox = draw.textbbox((0, 0), reflowed_headline, font=headline_font)
        summary_bbox = draw.textbbox((0, 0), reflowed_summary, font=summary_font)

        # Calculate the height for headline and summary
        headline_h = headline_bbox[3]  # Height is the fourth value
        summary_h = summary_bbox[3]  # Height is the fourth value

        total_height = headline_h + summary_h + 20  # Add space between headline and summary

        # Adjust the vertical centering by modifying headline_y
        headline_x = (w - max_width) / 2
        headline_y = (h - total_height) / 2  # Vertically center based on total height

        # x- and y-coordinates for the top left of the summary
        summary_x = headline_x
        summary_y = headline_y + headline_h + 20  # Maintain consistent spacing between headline and summary

        # Draw red rectangles to frame the article
        draw.rectangle((padding / 4, padding / 4, w - (padding / 4), headline_y - (padding / 4)), fill=inky_display.RED)
        draw.rectangle((padding / 4, summary_y + summary_h + (padding / 4) + 5, w - (padding / 4), h - (padding / 4)), fill=inky_display.RED)

        # Add some white hatching to the red rectangles to make it look a bit more interesting
        hatch_spacing = 12
        for x in range(0, 2 * w, hatch_spacing):
            draw.line((x, 0, x - w, h), fill=inky_display.WHITE, width=3)

        # Write the headline in RED
        draw.multiline_text((headline_x, headline_y), reflowed_headline, fill=inky_display.RED, font=headline_font, align="left")

        # Write the summary in BLACK
        draw.multiline_text((summary_x, summary_y), reflowed_summary, fill=inky_display.BLACK, font=summary_font, align="left")

        # Display the completed canvas on Inky wHAT
        inky_display.set_image(img)
        inky_display.show()

        # Save the image (optional)
        img.putpalette((255, 255, 255, 0, 0, 0, 255, 0, 0) + (0, 0, 0) * 252)
        img = img.convert("RGB").quantize(palette=img)
        img.save('/home/pi/boopbox/static/img/inkyscreen.png')

    else:
        print("Unable to run BBC task")

# Scheduler jobs
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_and_filter_feeds, trigger="interval", minutes=30)
scheduler.add_job(func=get_articles, trigger="interval", minutes=1)

scheduler.start()



# Initialize the BBC feed and first article
fetch_and_filter_feeds()
print(global_feeds)
get_articles()



if __name__ == "__main__":
    # Start the Flask application
    app.run(host='0.0.0.0', port=8080)