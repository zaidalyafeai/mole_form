from datasets import Dataset, DownloadMode, load_dataset

masader = load_dataset(
    'arbml/masader',
    download_mode=DownloadMode.FORCE_REDOWNLOAD, ignore_verifications=True)['train']
print(masader)
print(masader[0])
print(masader[-1])