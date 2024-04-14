import joblib
from tensorflow.keras.models import Sequential, save_model, load_model

from tensorflow.keras.layers import Dense


# Load the model weights using joblib
loaded_weights = joblib.load("ImageNet.joblib")

# Create a new Keras model (replace 'Sequential' and 'Dense' with your actual model architecture)
new_model = Sequential()
new_model.add(Dense(units=your_units, input_shape=your_input_shape))
# Add more layers as per your original model architecture

# Set the weights of the new model with the loaded weights
new_model.set_weights(loaded_weights)

# Save the new model in HDF5 format using save_model
save_model(new_model, "ImageNet.h5")

# Confirm successful conversion
print("Model successfully converted to HDF5 format.")
