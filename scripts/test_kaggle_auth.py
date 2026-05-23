from kaggle.api.kaggle_api_extended import KaggleApi
api = KaggleApi()
api.authenticate()
print('auth ok')
files = api.dataset_list_files('zynicide/wine-reviews')
print('files:', [f.name for f in files.files[:5]])
