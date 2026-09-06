import pandas as pd
import streamlit as st
from sklearn.linear_model import LinearRegression

DATA_FILE = "data/price_history.csv"
data = pd.read_csv(DATA_FILE)
data["date"] = pd.to_datetime(data["date"])

st.title("PriceSense")
st.write("A Machine-Learning Based Price Predictor")

st.header("Dataset Overview")
number_of_records = len(data)
number_of_products = data["product_id"].nunique()
st.write("Number of records:", number_of_records)
st.write("Number of Products:", number_of_products)

st.header("Explore Product:")
products = data["product_id"].unique()
selected_product = st.selectbox(
    "Select a product:",
    products
)

product_data = data[
    data["product_id"] == selected_product
].copy()
product_data = product_data.sort_values("date")

st.subheader("Historical Price:")
st.line_chart(
    product_data.set_index("date")["price"]
)

product_data["days"] = (
    product_data["date"] -
    product_data["date"].min()
).dt.days

X = product_data[["days"]]

y = product_data["price"]

model = LinearRegression()
model.fit(X, y)

next_day = product_data["days"].max() + 1
predicted_price = model.predict(
    [[next_day]]
)[0]

latest_price = product_data.iloc[-1]["price"]
st.subheader("Price Prediction")
st.metric(
    "Latest Price",
    f"₹{latest_price:,.2f}"
)
st.metric(
    "Predicted Next-Day Price",
    f"₹{predicted_price:,.2f}"
)